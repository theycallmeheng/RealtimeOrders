import asyncio
import hmac
import hashlib
import io
import json
import logging
import time
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from functools import wraps
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.openapi.docs import get_swagger_ui_html
from PIL import Image, UnidentifiedImageError, ImageOps
from sqlalchemy import select, update, func, or_
from sqlalchemy.exc import IntegrityError, OperationalError
from .config import settings
from .db import T, Session, engine, reflect, now, uid, uuid, one, rows, add, change, check, text, public, Fault
from . import auth, commerce, accounts, admin, chat, menus, shipping, analytics
from .events import emit, flush_events, outbox_worker, session_monitor, hub, Subscriber, event_wire
from .moderation import sanitize

log=logging.getLogger('realtimeorders')

@asynccontextmanager
async def lifespan(app):
    await reflect()
    task=asyncio.create_task(outbox_worker())
    monitor=asyncio.create_task(session_monitor())
    schedule=asyncio.create_task(menus.boundary_monitor())
    yield
    task.cancel()
    monitor.cancel()
    schedule.cancel()
    with suppress(asyncio.CancelledError): await task
    with suppress(asyncio.CancelledError): await monitor
    with suppress(asyncio.CancelledError): await schedule
    await engine.dispose()

app=FastAPI(title='RealtimeOrders API',version='1.0.0',lifespan=lifespan)

@app.get('/api/openapi.json',include_in_schema=False)
async def openapi_schema():return app.openapi()

@app.get('/api/docs',include_in_schema=False)
async def api_documentation():return get_swagger_ui_html(openapi_url='/api/openapi.json',title='RealtimeOrders API')

@app.middleware('http')
async def boundaries(request,call_next):
    request.state.request_id=uid()
    response=await call_next(request)
    response.headers['X-Request-ID']=request.state.request_id
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    return response

def error_response(request,code,message,status,details=None):
    return JSONResponse({'error':{'code':code,'message':message,'details':details},
                         'requestId':getattr(request.state,'request_id',uid())},status_code=status)

@app.exception_handler(Fault)
async def fault_handler(request,exc): return error_response(request,exc.code,exc.message,exc.status,exc.details)

@app.exception_handler(IntegrityError)
async def integrity_handler(request,exc):
    # DB statement parameters may contain secrets. Never log exception text here.
    log.warning('database_conflict requestId=%s',request.state.request_id)
    return error_response(request,'DATA_CONFLICT','Dữ liệu trùng hoặc đã được tham chiếu. Vui lòng tải lại.',409)

@app.exception_handler(OperationalError)
async def operational_handler(request,exc):
    log.error('database_unavailable requestId=%s',request.state.request_id)
    return error_response(request,'RETRY_REQUIRED','Dịch vụ đang bận. Hãy gửi lại cùng mã thao tác.',503)

@app.exception_handler(Exception)
async def unexpected_handler(request,exc):
    log.error('unexpected_error type=%s requestId=%s',type(exc).__name__,request.state.request_id)
    return error_response(request,'INTERNAL_ERROR','Có lỗi xử lý; mã lỗi đã được ghi nhận.',500)

async def body_json(request):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk); check(len(raw)<=65536,'FRAME_TOO_LARGE','Dữ liệu vượt 64 KiB',413)
    try: body=json.loads(raw) if raw else {}
    except (ValueError,UnicodeError,RecursionError): raise Fault('INVALID_JSON','JSON không hợp lệ')
    check(isinstance(body,dict),'INVALID_JSON','Nội dung phải là JSON object')
    pending=[(body,0)]
    while pending:
        value,depth=pending.pop()
        check(depth<=32,'INVALID_JSON','JSON lồng quá sâu')
        if isinstance(value,dict):pending.extend((item,depth+1) for item in value.values())
        elif isinstance(value,list):pending.extend((item,depth+1) for item in value)
    return body

def origin_check(request):
    check(request.headers.get('origin')==settings.app_origin,'ORIGIN_REJECTED','Nguồn truy cập không được cho phép',403)

def csrf_check(request):
    origin_check(request)
    raw=request.cookies.get('ro_session','')
    check(bool(raw) and hmac.compare_digest(request.headers.get('x-csrf-token',''),auth.csrf(raw)),
          'CSRF_REJECTED','Phiên xác nhận không hợp lệ; vui lòng tải lại',403)

def route(method,path,anonymous=False,idempotent=False):
    def decorator(handler):
        async def endpoint(request:Request):
            body=await body_json(request) if method!='GET' else {}
            if '/product-requests' in path:
                raise Fault('FEATURE_RETIRED','Chức năng yêu cầu hàng và báo giá đã ngừng hỗ trợ',410)
            if method!='GET':
                if anonymous: origin_check(request)
                else: csrf_check(request)
            async with Session.begin() as s:
                s.info['request_id']=request.state.request_id
                user=None if anonymous else await auth.authenticate(s,request.cookies.get('ro_session'),activity=method!='GET')
                if path.startswith('/admin'): auth.require_admin(user)
                key=request.headers.get('idempotency-key') if idempotent else None
                scope='http:'+method+':'+path
                prior=await commerce.idem(s,user,scope,key,body) if key is not None else None
                if prior is not None:
                    result=prior
                else:
                    result=await handler(s,user,body,request)
                    if key is not None: await commerce.complete(s,user,scope,key,result)
                await flush_events(s)
            return result if isinstance(result,(JSONResponse,FileResponse)) else JSONResponse(public(result))
        endpoint.__name__=handler.__name__
        app.add_api_route('/api/v1'+path,endpoint,methods=[method],name=handler.__name__)
        return handler
    return decorator

@app.get('/api/health')
async def health():
    async with engine.connect() as c: await c.execute(select(1))
    return {'status':'ok','demo':settings.demo_mode,'version':'1.0.0'}

@app.post('/api/v1/auth/{kind}/otp')
async def otp(kind:str,request:Request):
    origin_check(request); b=await body_json(request)
    check(kind in ('registration','password-reset'),'NOT_FOUND','Không có chức năng này',404)
    subject=auth.phone(b.get('phone'))
    user=None
    async with Session.begin() as s:
        user=await one(s,'users',T['users'].c.phone_e164==subject,required=False)
    if kind=='registration': check(not user,'PHONE_USED','Số điện thoại đã được đăng ký',409)
    # Do not send password-reset OTPs for unknown/locked identities.
    if kind=='password-reset' and (not user or user['status']!='ACTIVE'):
        await auth.rate('otp-ip:'+request.client.host,20,3600)
        return {'challengeId':uid(),'expiresIn':300,'demo':settings.demo_mode}
    if kind=='registration':
        return await auth.registration_challenge(subject,request.client.host)
    return await auth.challenge(subject,'RESET_PASSWORD',request.client.host,user)

@app.post('/api/v1/auth/registration/sms-fallback')
async def registration_sms_fallback(request:Request):
    origin_check(request); b=await body_json(request)
    return await auth.sms_fallback(uuid(b.get('challengeId')),request.client.host)

@app.post('/api/v1/auth/{kind}/verify')
async def verify(kind:str,request:Request):
    origin_check(request); b=await body_json(request)
    purposes={'registration':'REGISTER_PHONE','password-reset':'RESET_PASSWORD','email':'VERIFY_EMAIL'}
    check(kind in purposes,'NOT_FOUND','Không có chức năng này',404)
    await auth.rate('otp-verify:'+request.client.host,100,3600)
    result=await auth.verify_challenge(uuid(b.get('challengeId')),text(b.get('code'),6,6),purposes[kind])
    if kind=='email':
        csrf_check(request)
        async with Session.begin() as s:
            user=await auth.authenticate(s,request.cookies.get('ro_session'),activity=True)
            c=await auth.consume(s,result['ticket'],'VERIFY_EMAIL')
            check(c['user_id']==user['id'],'FORBIDDEN','Xác minh không thuộc tài khoản này',403)
            await change(s,'users',user['id'],email_normalized=c['subject'],email_verified_at=now(),updated_at=now(),version=user['version']+1)
        return {'ok':True}
    return result

@route('POST','/auth/register',anonymous=True)
async def register(s,user,b,r):
    c=await auth.consume(s,b.get('ticket'),'REGISTER_PHONE')
    group=await one(s,'customer_groups',T['customer_groups'].c.code=='WORKER',T['customer_groups'].c.active==True)
    id=uid()
    name=await sanitize(s,None,text(b.get('displayName'),100,1),'display_name')
    await add(s,'users',id=id,phone_e164=c['subject'],password_hash=await auth.password_hash(b.get('password')),
              display_name=name,role='CUSTOMER',status='ACTIVE',group_id=group['id'],phone_verified_at=now(),
              security_version=1,version=1,created_at=now(),updated_at=now())
    created=await one(s,'users',T['users'].c.id==id)
    # Record registration moderation once there is an owner.
    await sanitize(s,created,text(b.get('displayName'),100,1),'display_name',id)
    return {'user':auth.profile(created)}

@app.post('/api/v1/auth/login')
async def login(request:Request):
    origin_check(request); b=await body_json(request)
    await auth.rate('login-ip:'+request.client.host,100,3600)
    await auth.rate('login-id:'+str(b.get('identifier','')).casefold(),20,900)
    password=b.get('password')
    check(isinstance(password,str) and 1<=len(password)<=128,'INVALID_PASSWORD','Mật khẩu không hợp lệ')
    async with Session.begin() as s: user,raw=await auth.login(s,b.get('identifier'),password)
    result=JSONResponse(public({'user':auth.profile(user),'csrfToken':auth.csrf(raw),'demo':settings.demo_mode}))
    result.set_cookie('ro_session',raw,max_age=settings.session_seconds,httponly=True,secure=settings.cookie_secure,samesite='strict',path='/')
    return result

@route('GET','/auth/session')
async def session(s,user,b,r): return {'user':auth.profile(user),'csrfToken':auth.csrf(r.cookies['ro_session']),'demo':settings.demo_mode}

@route('POST','/auth/activity')
async def activity(s,user,b,r): return {'ok':True}

@route('POST','/auth/logout')
async def logout(s,user,b,r):
    await s.execute(update(T['sessions']).where(T['sessions'].c.token_hash==auth.hashed(r.cookies['ro_session'])).values(revoked_at=now()))
    result=JSONResponse({'ok':True}); result.delete_cookie('ro_session',path='/',secure=settings.cookie_secure,httponly=True,samesite='strict')
    return result

@route('POST','/auth/password-reset/confirm',anonymous=True)
async def reset_password(s,user,b,r):
    c=await auth.consume(s,b.get('ticket'),'RESET_PASSWORD')
    user=await commerce.lock_user(s,c['user_id'])
    check(user['status']=='ACTIVE','ACCOUNT_LOCKED','Tài khoản không hoạt động',403)
    await change(s,'users',user['id'],password_hash=await auth.password_hash(b.get('password')),security_version=user['security_version']+1,updated_at=now())
    await s.execute(update(T['sessions']).where(T['sessions'].c.user_id==user['id']).values(revoked_at=now()))
    emit(s,'user:'+user['id'],'SESSION_REVOKED',{'message':'Mật khẩu đã được đổi.'})
    return {'ok':True}

@app.post('/api/v1/auth/email/challenge')
async def email_challenge(request:Request):
    csrf_check(request); b=await body_json(request)
    async with Session.begin() as s: user=await auth.authenticate(s,request.cookies.get('ro_session'),activity=True)
    return await auth.challenge(auth.email(b.get('email')),'VERIFY_EMAIL',request.client.host,user)

@route('PATCH','/me')
async def edit_profile(s,user,b,r):
    user=await commerce.lock_user(s,user['id']); commerce.version(user,b)
    await change(s,'users',user['id'],display_name=await sanitize(s,user,text(b.get('displayName'),100,1),'display_name'),version=user['version']+1,updated_at=now())
    return auth.profile(await one(s,'users',T['users'].c.id==user['id']))

@route('GET','/me/addresses')
async def list_addresses(s,u,b,r): return await accounts.addresses(s,u,'GET',None,b)
@route('POST','/me/addresses',idempotent=True)
async def new_address(s,u,b,r): return await accounts.addresses(s,u,'POST',None,b)
@route('PATCH','/me/addresses/{id}')
async def edit_address(s,u,b,r): return await accounts.addresses(s,u,'PATCH',uuid(r.path_params['id']),b)
@route('DELETE','/me/addresses/{id}')
async def delete_address(s,u,b,r): return await accounts.addresses(s,u,'DELETE',uuid(r.path_params['id']),b)

@route('GET','/catalog/offers')
async def offers(s,u,b,r): return await commerce.catalog(s,u)
@route('GET','/delivery/options')
async def delivery_options(s,u,b,r):
    return {'zones':await rows(s,'delivery_zones',T['delivery_zones'].c.active==True),
            'policies':await rows(s,'delivery_policies',T['delivery_policies'].c.group_id==u['group_id'],T['delivery_policies'].c.active==True),
            'pickupSlots':await rows(s,'pickup_slots',T['pickup_slots'].c.active==True,T['pickup_slots'].c.ends_at>now())}

@route('POST','/orders')
async def place_order(s,u,b,r): return await commerce.create_order(s,u,b,r.headers.get('idempotency-key'))

def page_offset(r):
    try: return max(0,min(int(r.query_params.get('page','0')),400))*50
    except ValueError: raise Fault('INVALID_PAGE','Trang không hợp lệ')

async def order_list(s,u,r,all=False):
    t=T['orders']; q=select(t.c.id).order_by(t.c.created_at.desc(),t.c.id.desc()).limit(50).offset(page_offset(r))
    if not all: q=q.where(t.c.customer_id==u['id'])
    if r.query_params.get('status'): q=q.where(t.c.status==r.query_params['status'])
    ids=(await s.execute(q)).scalars().all()
    return [await commerce.get_order(s,u,id) for id in ids]

@route('GET','/orders')
async def list_orders(s,u,b,r): return await order_list(s,u,r)
@route('GET','/orders/by-client-id/{id}')
async def order_by_client(s,u,b,r):
    o=await one(s,'orders',T['orders'].c.customer_id==u['id'],T['orders'].c.client_order_id==uuid(r.path_params['id']))
    return await commerce.get_order(s,u,o['id'])
@route('GET','/orders/{id}')
async def order_detail(s,u,b,r): return await commerce.get_order(s,u,uuid(r.path_params['id']))
@route('POST','/orders/{id}/{action}')
async def customer_order_action(s,u,b,r):
    action=r.path_params['action']; action='request-cancel' if action=='cancellation-requests' else action
    check(action in ('cancel','request-cancel'),'NOT_FOUND','Thao tác không tồn tại',404)
    return await commerce.order_action(s,u,uuid(r.path_params['id']),action,b,r.headers.get('idempotency-key'))
@route('GET','/admin/orders')
async def admin_orders(s,u,b,r): return await order_list(s,u,r,all=True)
@route('POST','/admin/orders/{id}/{action}')
async def admin_order_action(s,u,b,r):
    check(r.path_params['action'] in ('approve','reject','transition','decide-cancel'),'NOT_FOUND','Thao tác không tồn tại',404)
    return await commerce.order_action(s,u,uuid(r.path_params['id']),r.path_params['action'],b,r.headers.get('idempotency-key'))

@route('POST','/product-requests')
@route('GET','/product-requests')
@route('GET','/product-requests/{id}')
@route('POST','/product-requests/{id}/{action}')
@route('GET','/admin/product-requests')
@route('POST','/admin/product-requests/{id}/{action}')
async def retired_requests(s,u,b,r):
    raise Fault('FEATURE_RETIRED','Chức năng yêu cầu hàng và báo giá đã ngừng hỗ trợ',410)

@route('GET','/conversations/me')
async def my_conversation(s,u,b,r): return await chat.conversation(s,u)
@route('GET','/conversations/{id}/messages')
async def conversation_messages(s,u,b,r): return await chat.messages(s,u,uuid(r.path_params['id']),r.query_params.get('before'))
@route('POST','/conversations/{id}/messages')
async def chat_message(s,u,b,r):
    await auth.rate('chat:'+u['id'],30,60)
    b['conversationId']=uuid(r.path_params['id']); return await chat.send(s,u,b)
@route('GET','/admin/conversations')
async def admin_conversations(s,u,b,r):
    c,users=T['conversations'],T['users']
    return [dict(x) for x in (await s.execute(select(c,users.c.display_name).join(users,c.c.customer_id==users.c.id)
        .order_by(c.c.created_at.desc()).limit(50).offset(page_offset(r)))).mappings()]

@route('GET','/notifications')
async def notifications(s,u,b,r):
    return await menus.notification_feed(s,u,page_offset(r))
@route('POST','/notifications/{id}/read')
async def notification_read(s,u,b,r):
    n=await one(s,'notifications',T['notifications'].c.id==uuid(r.path_params['id']),T['notifications'].c.user_id==u['id'])
    await change(s,'notifications',n['id'],read_at=now()); emit(s,'user:'+u['id'],'NOTIFICATION_READ',{'id':n['id']})
    return {'ok':True}
@route('POST','/subscriptions/products/{id}')
async def subscribe(s,u,b,r):
    from sqlalchemy.dialects.mysql import insert
    id=uuid(r.path_params['id']); await one(s,'products',T['products'].c.id==id)
    t=T['product_subscriptions']; await s.execute(insert(t).values(user_id=u['id'],product_id=id,created_at=now()).on_duplicate_key_update(product_id=id))
    emit(s,'user:'+u['id'],'SUBSCRIPTION_CHANGED',{'productId':id,'enabled':True})
    return {'ok':True}
@route('DELETE','/subscriptions/products/{id}')
async def unsubscribe(s,u,b,r):
    t=T['product_subscriptions']; await s.execute(t.delete().where(t.c.user_id==u['id'],t.c.product_id==uuid(r.path_params['id'])))
    emit(s,'user:'+u['id'],'SUBSCRIPTION_CHANGED',{'productId':uuid(r.path_params['id']),'enabled':False})
    return {'ok':True}

CONFIG_PATHS={'groups':'customer_groups','categories':'categories','units':'units','zones':'delivery_zones',
              'policies':'delivery_policies','pickup-slots':'pickup_slots','moderation-rules':'moderation_rules'}
@route('GET','/admin/config/{kind}')
async def config_list(s,u,b,r):
    table=CONFIG_PATHS.get(r.path_params['kind']); check(table,'NOT_FOUND','Không tìm thấy danh mục',404)
    return await rows(s,table,limit=500)
@route('POST','/admin/config/{kind}')
async def config_create(s,u,b,r):
    table=CONFIG_PATHS.get(r.path_params['kind']); check(table,'NOT_FOUND','Không tìm thấy danh mục',404)
    return await admin.configuration(s,u,table,None,b)
@route('PATCH','/admin/config/{kind}/{id}')
async def config_update(s,u,b,r):
    table=CONFIG_PATHS.get(r.path_params['kind']); check(table,'NOT_FOUND','Không tìm thấy danh mục',404)
    return await admin.configuration(s,u,table,uuid(r.path_params['id']),b,'PATCH')
@route('DELETE','/admin/config/{kind}/{id}')
async def config_delete(s,u,b,r):
    table=CONFIG_PATHS.get(r.path_params['kind']); check(table,'NOT_FOUND','Không tìm thấy danh mục',404)
    return await admin.configuration(s,u,table,uuid(r.path_params['id']),b,'DELETE')
@route('GET','/admin/products')
async def products(s,u,b,r):
    data=await rows(s,'products',limit=1000,order=[T['products'].c.active.desc(),T['products'].c.name])
    images=await rows(s,'product_images',T['product_images'].c.product_id.in_([p['id'] for p in data]),
                      limit=5000,order=T['product_images'].c.position)
    by_product={}
    for image in images:by_product.setdefault(image['product_id'],[]).append(image)
    for p in data:p['images']=by_product.get(p['id'],[])
    return data
@route('POST','/admin/products')
async def product_create(s,u,b,r): return await admin.product(s,u,None,b)
@route('PATCH','/admin/products/{id}')
async def product_update(s,u,b,r): return await admin.product(s,u,uuid(r.path_params['id']),b)
@route('DELETE','/admin/products/{id}')
async def product_delete(s,u,b,r): return await admin.product(s,u,uuid(r.path_params['id']),b,'DELETE')
@route('GET','/admin/offers')
async def admin_offers(s,u,b,r): return await commerce.catalog(s,u,admin=True)
@route('POST','/admin/offers')
async def offer_create(s,u,b,r): return await admin.offer(s,u,None,b)
@route('PATCH','/admin/offers/{id}')
async def offer_update(s,u,b,r): return await admin.offer(s,u,uuid(r.path_params['id']),b)
@route('POST','/admin/inventory-adjustments')
async def adjust_inventory(s,u,b,r): return await admin.adjustment(s,u,b,r.headers.get('idempotency-key'))
@route('GET','/admin/users')
async def users_list(s,u,b,r):
    q=select(T['users']).order_by(T['users'].c.created_at.desc()).limit(50).offset(page_offset(r))
    status=r.query_params.get('status')
    if status and status!='ALL': q=q.where(T['users'].c.status==status)
    elif status!='ALL': q=q.where(T['users'].c.status!='DELETED')
    return [auth.profile(dict(x)) for x in (await s.execute(q)).mappings()]
@route('PATCH','/admin/users/{id}')
async def update_user(s,u,b,r): return await accounts.user_action(s,u,uuid(r.path_params['id']),b)
@route('GET','/admin/users/{id}/delivery-context')
async def customer_delivery_context(s,u,b,r):
    customer=await one(s,'users',T['users'].c.id==uuid(r.path_params['id']))
    return {'addresses':await rows(s,'addresses',T['addresses'].c.user_id==customer['id'],T['addresses'].c.deleted_at==None),
            'policies':await rows(s,'delivery_policies',T['delivery_policies'].c.group_id==customer['group_id'],T['delivery_policies'].c.active==True),
            'pickupSlots':await rows(s,'pickup_slots',T['pickup_slots'].c.active==True,T['pickup_slots'].c.ends_at>now())}
@route('GET','/admin/moderation/violations')
async def violations(s,u,b,r): return await rows(s,'moderation_violations',limit=100,order=T['moderation_violations'].c.created_at.desc())
@route('GET','/admin/audit')
async def audit_list(s,u,b,r): return await rows(s,'audit_logs',limit=100,order=T['audit_logs'].c.created_at.desc())
@route('GET','/admin/inventory-movements')
async def movement_list(s,u,b,r): return await rows(s,'inventory_movements',limit=100,order=T['inventory_movements'].c.created_at.desc())
@route('GET','/admin/reports')
async def report(s,u,b,r):
    return await admin.reports(s,admin.date_time(r.query_params.get('start',str(now().date())+'T00:00:00Z')),
                               admin.date_time(r.query_params.get('end',str((now()+timedelta(days=1)).date())+'T00:00:00Z')))

@route('GET','/catalog/menu')
async def daily_catalog(s,u,b,r): return await menus.current(s,u)

@route('GET','/admin/menus')
async def menu_list(s,u,b,r):
    data=await rows(s,'daily_menus',limit=100,order=[T['daily_menus'].c.sale_date.desc(),T['daily_menus'].c.opens_at.desc()])
    return public(data)

@route('GET','/admin/menus/{id}')
async def menu_detail(s,u,b,r): return await menus.detail(s,uuid(r.path_params['id']))

@route('POST','/admin/menus',idempotent=True)
async def menu_create(s,u,b,r): return await menus.save(s,u,None,b)

@route('PATCH','/admin/menus/{id}',idempotent=True)
async def menu_update(s,u,b,r): return await menus.save(s,u,uuid(r.path_params['id']),b)

@route('POST','/admin/menus/{id}/copy',idempotent=True)
async def menu_copy(s,u,b,r): return await menus.copy(s,u,uuid(r.path_params['id']),b)

@route('GET','/admin/warehouse')
async def warehouse_get(s,u,b,r): return await shipping.warehouse(s)

@route('PATCH','/admin/warehouse')
async def warehouse_save(s,u,b,r): return await shipping.save_warehouse(s,u,b)

@route('GET','/admin/reports/daily')
async def daily_report(s,u,b,r): return await analytics.report(s,r.query_params.get('date'),r.query_params.get('compare'))

@route('GET','/maps/search')
async def location_search(s,u,b,r):
    await auth.rate('map:'+u['id'],30,60)
    return await shipping.search(r.query_params.get('q',''))

@route('GET','/maps/place')
async def location_resolve(s,u,b,r):
    await auth.rate('map:'+u['id'],30,60)
    return await shipping.resolve(r.query_params.get('id',''))

@app.post('/api/v1/delivery/quote')
async def delivery_quote(request:Request):
    csrf_check(request); body=await body_json(request)
    async with Session.begin() as s:
        user=await auth.authenticate(s,request.cookies.get('ro_session'),activity=True)
        prepared=await shipping.prepare(s,user,body)
    await auth.rate('route:'+user['id'],15,60)
    routed=await shipping.route(prepared[0],prepared[2])
    # Recheck versions after network I/O, using a new transaction.
    async with Session.begin() as s:
        current=await auth.authenticate(s,request.cookies.get('ro_session'))
        fresh=await shipping.prepare(s,current,body)
        check(current['id']==user['id'] and fresh==prepared,'REQUOTE_REQUIRED','Dữ liệu đã đổi khi tính phí; vui lòng thử lại',409)
        result=await shipping.record_quote(s,current,fresh,routed)
    return JSONResponse(public(result))

@app.post('/api/v1/media')
async def upload(request:Request):
    csrf_check(request)
    async with Session.begin() as s: user=await auth.authenticate(s,request.cookies.get('ro_session'),activity=True)
    await auth.rate('upload:'+user['id'],20,60)
    # Limit the entire multipart request before parsing, including malformed headers/parts.
    size=0; chunks=[]
    async for chunk in request.stream():
        size+=len(chunk); check(size<=6*1024*1024,'FILE_TOO_LARGE','Ảnh tối đa 5 MiB',413); chunks.append(chunk)
    request._body=b''.join(chunks)
    async with request.form(max_files=1,max_fields=3,max_part_size=6*1024*1024) as form:
        purpose=form.get('purpose','CHAT')
        check(purpose in ('CHAT','PRODUCT'),'INVALID_PURPOSE','Mục đích ảnh không hợp lệ')
        if purpose=='PRODUCT': auth.require_admin(user)
        file=form.get('file'); check(hasattr(file,'read'),'FILE_REQUIRED','Vui lòng chọn ảnh')
        raw=await file.read(5*1024*1024+1)
    check(len(raw)<=5*1024*1024,'FILE_TOO_LARGE','Ảnh tối đa 5 MiB',413)
    def clean_image():
        try:
            image=Image.open(io.BytesIO(raw))
            check(image.format in ('JPEG','PNG','WEBP') and image.width*image.height<=16000000,
                  'INVALID_IMAGE','Chỉ nhận JPEG, PNG, WebP tối đa 16 triệu pixel')
            image.load(); image=ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2400,2400))
            out=io.BytesIO(); image.save(out,format='JPEG',quality=88)
            return out.getvalue(),image.width,image.height
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError): raise Fault('INVALID_IMAGE','Tập tin không phải ảnh hợp lệ')
    data,width,height=await asyncio.to_thread(clean_image)
    id=uid(); key=id+'.jpg'; folder=Path(settings.upload_dir); folder.mkdir(parents=True,exist_ok=True)
    await asyncio.to_thread((folder/key).write_bytes,data)
    try:
        async with Session.begin() as s:
            await add(s,'media_assets',id=id,owner_id=user['id'],purpose=purpose,state='READY',storage_key=key,
                      mime_type='image/jpeg',size_bytes=len(data),width=width,height=height,
                      content_sha256=hashlib.sha256(data).digest(),created_at=now())
    except Exception:
        (folder/key).unlink(missing_ok=True); raise
    return {'id':id,'url':'/api/v1/media/'+id,'width':width,'height':height}

@route('GET','/media/{id}')
async def media(s,u,b,r):
    id=uuid(r.path_params['id']); asset=await one(s,'media_assets',T['media_assets'].c.id==id,T['media_assets'].c.state=='READY')
    allowed=u['role']=='ADMIN' or asset['owner_id']==u['id']
    if not allowed and asset['purpose']=='PRODUCT':
        allowed=any(id in offer['images'] for offer in await commerce.catalog(s,u))
    if not allowed and asset['purpose']=='CHAT':
        a,m,c=T['message_attachments'],T['messages'],T['conversations']
        allowed=bool((await s.execute(select(a.c.asset_id).join(m,a.c.message_id==m.c.id).join(c,m.c.conversation_id==c.c.id)
                     .where(a.c.asset_id==id,c.c.customer_id==u['id']).limit(1))).first())
    check(allowed,'FORBIDDEN','Ảnh thuộc hội thoại riêng tư',403)
    path=Path(settings.upload_dir)/asset['storage_key']
    check(path.is_file(),'NOT_FOUND','Không tìm thấy ảnh',404)
    return FileResponse(path,media_type=asset['mime_type'],headers={'Cache-Control':'private, max-age=60','X-Content-Type-Options':'nosniff'})

# WebSocket implementation is kept separate so transport cannot change domain rules.
from .realtime import serve_socket
app.add_api_websocket_route('/ws',serve_socket)
