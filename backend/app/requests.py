from datetime import timedelta, datetime
from decimal import Decimal
from sqlalchemy import select, func
from .db import T, now, uid, one, rows, add, change, check, text, number, uuid, public
from .commerce import version, lock_user, audit, create_order, delivery, idem, complete
from .auth import require_admin
from .events import emit, notify
from .moderation import sanitize

async def detail(s,user,id):
    req=await one(s,'product_requests',T['product_requests'].c.id==id)
    check(user['role']=='ADMIN' or req['customer_id']==user['id'],'FORBIDDEN','Không có quyền xem yêu cầu',403)
    req['quotes']=await rows(s,'request_quotes',T['request_quotes'].c.request_id==id,order=T['request_quotes'].c.revision.desc())
    linked=await one(s,'orders',T['orders'].c.source_request_id==id,required=False)
    req['linked_order']={k:linked[k] for k in ('id','status','version')} if linked else None
    req['history']=await rows(s,'request_status_history',T['request_status_history'].c.request_id==id,
                              order=T['request_status_history'].c.request_version)
    return public(req)

async def create(s,user,body):
    id=uid()
    req=await add(s,'product_requests',id=id,customer_id=user['id'],
        item_name=await sanitize(s,user,text(body.get('itemName'),150,1),'request.name',id),
        unit_label=text(body.get('unitLabel'),40,1),quantity=number(body.get('quantity'),minimum=Decimal('.001')),
        note=await sanitize(s,user,text(body.get('note',''),2000),'request.note',id),
        status='NEW',version=1,created_at=now(),updated_at=now())
    await history(s,user,req,None,'NEW',1)
    emit(s,'admin:ops','REQUEST_CHANGED',{'id':id,'status':'NEW'},id,1)
    return await detail(s,user,id)

async def history(s,user,req,old,target,v):
    await add(s,'request_status_history',id=uid(),request_id=req['id'],actor_id=user['id'],from_status=old,
              to_status=target,request_version=v,created_at=now())

async def action(s,user,id,action,body,key=None):
    scope='request-convert:'+id
    if action=='convert':
        prior=await idem(s,user,scope,key,body)
        if prior: return prior
    req=await one(s,'product_requests',T['product_requests'].c.id==id)
    await lock_user(s,req['customer_id'])
    req=await one(s,'product_requests',T['product_requests'].c.id==id,lock=True)
    admin=user['role']=='ADMIN'
    check(admin or user['id']==req['customer_id'],'FORBIDDEN','Không có quyền xử lý',403)
    if action=='convert' and req['status']=='CONVERTED':
        return await complete(s,user,scope,key,await detail(s,user,id))
    version(req,body)
    status=req['status']
    if action=='receive':
        require_admin(user); check(status=='NEW','INVALID_STATE','Yêu cầu đã được xử lý',409); target='RECEIVED'
    elif action=='reject':
        require_admin(user); check(status in ('NEW','RECEIVED','QUOTED'),'INVALID_STATE','Không thể từ chối',409); target='REJECTED'
    elif action=='cancel':
        check(not admin and status in ('NEW','RECEIVED','QUOTED','ACCEPTED'),'INVALID_STATE','Không thể hủy yêu cầu',409); target='CANCELLED'
    elif action=='quote':
        require_admin(user)
        check(status in ('RECEIVED','QUOTED'),'INVALID_STATE','Cần tiếp nhận yêu cầu trước; không sửa báo giá đã chấp thuận',409)
        offer=await one(s,'offers',T['offers'].c.id==uuid(body.get('offerId')),lock=True)
        check(offer['status']=='OPEN','OFFER_CLOSED','Chọn đợt hàng đang mở',409)
        customer=await one(s,'users',T['users'].c.id==req['customer_id'])
        qty=number(body.get('quantity'),minimum=Decimal('.001'))
        product=await one(s,'products',T['products'].c.id==offer['product_id'])
        check(qty%product['quantity_step']==0,'INVALID_STEP','Số lượng báo giá không đúng bước đơn vị')
        unit=await one(s,'units',T['units'].c.id==product['unit_id'])
        unitprice=number(body.get('unitPrice'),places=0)
        address,policy,shipping=await delivery(s,customer,body,qty*unitprice)
        expiry=int(number(body.get('expiresMinutes',60),places=0,minimum=Decimal(1),maximum=Decimal(1440)))
        revision=(await s.execute(select(func.coalesce(func.max(T['request_quotes'].c.revision),0))
                    .where(T['request_quotes'].c.request_id==id))).scalar_one()+1
        await add(s,'request_quotes',id=uid(),request_id=id,revision=revision,created_by=user['id'],offer_id=offer['id'],
                  quantity=qty,unit_price=unitprice,shipping_fee=policy['shipping_fee'],delivery_snapshot=shipping,
                  item_snapshot={'productName':product['name'],'unitLabel':unit['label'],'quantityStep':str(product['quantity_step'])},
                  expires_at=now()+timedelta(minutes=expiry),created_at=now())
        target='QUOTED'
    elif action in ('accept-quote','convert'):
        check(not admin,'FORBIDDEN','Khách hàng tự chấp thuận báo giá',403)
        quote=await one(s,'request_quotes',T['request_quotes'].c.id==uuid(body.get('quoteId')),
                        T['request_quotes'].c.request_id==id,lock=True)
        latest=(await s.execute(select(func.max(T['request_quotes'].c.revision)).where(T['request_quotes'].c.request_id==id))).scalar_one()
        check(quote['revision']==latest and quote['expires_at']>now(),'QUOTE_EXPIRED','Báo giá đã hết hạn hoặc được thay mới',409)
        if action=='accept-quote':
            check(status=='QUOTED','INVALID_STATE','Yêu cầu chưa có báo giá cần chấp thuận',409)
            await change(s,'request_quotes',quote['id'],accepted_at=now()); target='ACCEPTED'
        else:
            check(status=='ACCEPTED' and quote['accepted_at'],'INVALID_STATE','Cần chấp thuận báo giá trước',409)
            orderbody=dict(body)
            orderbody['items']=[{'offerId':quote['offer_id'],'quantity':str(quote['quantity'])}]
            await create_order(s,user,orderbody,key,quote=quote)
            target='CONVERTED'
    else: check(False,'UNKNOWN_ACTION','Thao tác không hợp lệ')
    await change(s,'product_requests',id,status=target,version=req['version']+1,updated_at=now())
    await history(s,user,req,status,target,req['version']+1)
    for topic in ('user:'+req['customer_id'],'admin:ops'):
        emit(s,topic,'REQUEST_CHANGED',{'id':id,'status':target,'version':str(req['version']+1)},id,req['version']+1)
    await notify(s,req['customer_id'],'REQUEST_STATUS',{'id':id,'status':target,'message':'Yêu cầu mua hàng vừa được cập nhật.'})
    await audit(s,user,'request.'+action,'product_request',id,{'status':status},{'status':target})
    result=await detail(s,user,id)
    return await complete(s,user,scope,key,result) if action=='convert' else result
