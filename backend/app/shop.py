"""Shop operations, delivery assignment, reviews and money reconciliation."""
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select, func, update
from . import auth, commerce, payments
from .db import T, now, uid, uuid, one, rows, add, change, check, text, number, public
from .events import emit, notify

DEFAULT_PROFILE = {'name':'RealtimeOrders','description':'','address':'96A Trần Phú, Hà Đông, Hà Nội','phone':'',
                   'businessType':'INDIVIDUAL','taxCode':'','registrationNumber':'','logoUrl':'','coverUrl':''}


async def setting(s, key):
    item=await one(s,'system_settings',T['system_settings'].c.setting_key==key,required=False)
    return {'value':item['value_json'] if item else DEFAULT_PROFILE,'version':str(item['version']) if item else '0'}


async def save_setting(s,user,key,body):
    auth.require_admin(user) if key=='vat_policy' else auth.require_shop(user)
    old=await one(s,'system_settings',T['system_settings'].c.setting_key==key,required=False,lock=True)
    check(str(body.get('expectedVersion'))==str(old['version'] if old else 0),'VERSION_CONFLICT','Cấu hình đã thay đổi',409)
    if key=='vat_policy': value={'rate':str(number(body.get('rate'),places=2,maximum=Decimal(100)))}
    else:
        value={k:text(body.get(k,''),2000 if k=='description' else 2048 if k.endswith('Url') else 200,1 if k=='name' else 0) for k in DEFAULT_PROFILE}
        check(value['businessType'] in ('INDIVIDUAL','HOUSEHOLD','COMPANY'),'INVALID_PROFILE','Loại hình không hợp lệ')
        from .admin import product_image_url
        for k in ('logoUrl','coverUrl'):
            if value[k]: value[k]=product_image_url(value[k])
    values={'value_json':value,'version':old['version']+1 if old else 1,'updated_by':user['id'],'updated_at':now()}
    if old: await s.execute(update(T['system_settings']).where(T['system_settings'].c.setting_key==key).values(**values))
    else: await add(s,'system_settings',setting_key=key,**values)
    await commerce.audit(s,user,'shop.'+key,'setting',key,old,values)
    emit(s,'admin:ops','CONFIG_CHANGED',{'table':key})
    for g in await rows(s,'customer_groups',T['customer_groups'].c.active==True):emit(s,'catalog:'+g['id'],'SHOP_CHANGED',{'refresh':True})
    return await setting(s,key)


async def profile(s, user, shop_id=None):
    from .marketplace import manage_shop
    shop = await manage_shop(s, user, shop_id)
    return {'value': {**DEFAULT_PROFILE, **shop['profile_json'], 'name': shop['name']}, 'version': str(shop['version'])}


async def save_profile(s, user, body):
    from .marketplace import manage_shop, shop_topic
    from .admin import product_image_url
    shop = await manage_shop(s, user, body.get('shopId'), lock=True)
    commerce.version(shop, body)
    existing = {**DEFAULT_PROFILE, **shop['profile_json']}
    fields = {key: text(body.get(key, existing[key]), 2000 if key == 'description' else 2048 if key.endswith('Url') else 200,
                        1 if key == 'name' else 0) for key in DEFAULT_PROFILE}
    check(fields['businessType'] in ('INDIVIDUAL', 'HOUSEHOLD', 'COMPANY'), 'INVALID_PROFILE', 'Loại hình không hợp lệ')
    for key in ('logoUrl', 'coverUrl'):
        if fields[key]:
            fields[key] = product_image_url(fields[key])
    await change(s, 'shops', shop['id'], name=fields['name'], profile_json=fields, version=shop['version']+1, updated_at=now())
    await commerce.audit(s, user, 'shop.profile', 'shop', shop['id'], None, {'name': fields['name']})
    emit(s, 'admin:ops', 'SHOP_CHANGED', {'refresh': True})
    emit(s, shop_topic(shop['id']), 'SHOP_CHANGED', {'refresh': True})
    for group in await rows(s, 'customer_groups', T['customer_groups'].c.active.is_(True)):
        emit(s, 'catalog:'+group['id'], 'SHOP_CHANGED', {'refresh': True})
    return await profile(s, user, shop['id'])


async def feed(s,user,shop_id=None):
    check(user['role']=='CUSTOMER','FORBIDDEN','Bảng tin dành cho khách hàng',403)
    from .menus import current
    from .marketplace import list_shops
    current_menu = await current(s, user, shop_id)
    shops = await list_shops(s)
    by_id = {shop['id']: shop for shop in shops}
    posts = []
    for menu in current_menu['menus']:
        offers = [offer for offer in current_menu['offers'] if offer['menu_id'] == menu['id']]
        if offers:
            posts.append({**menu, 'shop': by_id.get(menu['shop_id']), 'offers': offers})
    return {'shop': {'value': by_id.get(shop_id) or (shops[0] if shops else DEFAULT_PROFILE)}, 'shops': shops, 'posts': posts}


async def staff(s,user,body=None):
    if body is None:
        auth.require_shop(user)
        people=await rows(s,'users',T['users'].c.role.in_(('SELLER','SHIPPER')),T['users'].c.status!='DELETED',limit=200)
        if user['role']=='SELLER': return [{'id':p['id'],'display_name':p['display_name'],'role':p['role'],'status':p['status']} for p in people if p['role']=='SHIPPER']
        return [auth.profile(p) for p in people]
    auth.require_admin(user)
    check(body.get('role') in ('SELLER','SHIPPER'),'INVALID_ROLE','Chọn người bán hoặc người giao hàng')
    g=await one(s,'customer_groups',T['customer_groups'].c.code=='WORKER')
    from .marketplace import manage_shop
    seller_shop=await manage_shop(s,user,body.get('shopId')) if body['role']=='SELLER' else None
    person=await add(s,'users',id=uid(),shop_id=seller_shop['id'] if seller_shop else None,phone_e164=auth.phone(body.get('phone')),display_name=text(body.get('name'),100,1),
                     password_hash=await auth.password_hash(body.get('password')),role=body['role'],status='ACTIVE',group_id=g['id'],
                     phone_verified_at=now(),security_version=1,version=1,created_at=now(),updated_at=now())
    await commerce.audit(s,user,'staff.create','user',person['id'],None,{'role':person['role']})
    return auth.profile(await one(s,'users',T['users'].c.id==person['id']))


async def order_command(s,user,id,action,body,key):
    initial=await one(s,'orders',T['orders'].c.id==id)
    check(commerce.can_read_order(user,initial),'FORBIDDEN','Không có quyền xử lý đơn',403)
    prior=await commerce.idem(s,user,'fulfill:'+id+':'+action,key,body)
    if prior:return prior
    await commerce.lock_user(s,initial['customer_id'])
    o=await one(s,'orders',T['orders'].c.id==id,lock=True)
    commerce.version(o,body)
    if action=='assign':
        auth.require_shop(user)
        check(o['status'] in ('APPROVED','PREPARING','READY_FOR_PICKUP','DELIVERY_FAILED'),'INVALID_STATE','Chỉ phân công trước bàn giao hoặc khi giao thất bại',409)
        person=await one(s,'users',T['users'].c.id==uuid(body.get('courierId')),T['users'].c.role=='SHIPPER',T['users'].c.status=='ACTIVE')
        await change(s,'orders',id,courier_id=person['id'])
        if o.get('courier_id') and o['courier_id']!=person['id']:emit(s,'courier:'+o['courier_id'],'ASSIGNMENT_REVOKED',{'id':id})
        o['courier_id']=person['id']
        await notify(s,person['id'],'ORDER_ASSIGNED',{'id':id,'message':'Bạn vừa được phân công đơn giao/trao hàng.'})
        target=o['status']
    elif action=='delivery-failed':
        check(auth.is_shop(user) or (user['role']=='SHIPPER' and o['courier_id']==user['id']),'FORBIDDEN','Không có quyền giao đơn',403)
        check(o['status'] in ('SHIPPING','READY_FOR_PICKUP'),'INVALID_STATE','Đơn chưa được bàn giao',409)
        check(text(body.get('reason'),500,1),'REASON_REQUIRED','Cần lý do')
        target='DELIVERY_FAILED'
    elif action=='retry-delivery':
        auth.require_shop(user);check(o['status']=='DELIVERY_FAILED','INVALID_STATE','Đơn chưa giao thất bại',409)
        check(o['courier_id'],'COURIER_REQUIRED','Phân công người giao trước')
        await one(s,'users',T['users'].c.id==o['courier_id'],T['users'].c.status=='ACTIVE',T['users'].c.role=='SHIPPER')
        target='READY_FOR_PICKUP' if o['delivery_method']=='COLLECTIVE' else 'SHIPPING'
    elif action=='confirm-return':
        auth.require_shop(user);check(o['status']=='DELIVERY_FAILED','INVALID_STATE','Chỉ hoàn kho đơn giao thất bại',409)
        check(body.get('received') is True,'RETURN_REQUIRED','Xác nhận đã nhận đủ hàng hoàn',409)
        items=await rows(s,'order_items',T['order_items'].c.order_id==id,limit=100,order=T['order_items'].c.offer_id)
        for i in items:
            offer=await one(s,'offers',T['offers'].c.id==i['offer_id'],lock=True)
            await commerce.move_stock(s,user,offer,i['quantity'],'DELIVERY_RETURN',id,id)
        await commerce.catalog_event(s,[i['offer_id'] for i in items])
        target='CANCELLED'
    else:check(False,'UNKNOWN_ACTION','Thao tác không hợp lệ')
    await change(s,'orders',id,status=target,version=o['version']+1,updated_at=now(),**({'cancelled_at':now()} if target=='CANCELLED' else {}))
    await add(s,'order_status_history',id=uid(),order_id=id,actor_id=user['id'],from_status=o['status'],to_status=target,order_version=o['version']+1,reason=text(body.get('reason',''),500),created_at=now())
    fresh=await one(s,'orders',T['orders'].c.id==id)
    if target=='CANCELLED':
        await s.execute(update(T['cancellation_requests']).where(T['cancellation_requests'].c.order_id==id,T['cancellation_requests'].c.state=='OPEN').values(state='ACCEPTED',decision_by=user['id'],decision_note='Đã nhận hàng hoàn',decided_at=now()))
        await payments.request_refund(s,fresh)
    await payments.changed(s,fresh)
    await commerce.audit(s,user,'order.'+action,'order',id,{'status':o['status']},{'status':target,'courier_id':fresh['courier_id']})
    await notify(s,o['customer_id'],'ORDER_STATUS',{'id':id,'message':'Đơn hàng vừa được cập nhật.','status':target})
    return await commerce.complete(s,user,'fulfill:'+id+':'+action,key,await commerce.get_order(s,user,id))


async def review(s,user,order_id,body):
    o=await one(s,'orders',T['orders'].c.id==order_id,T['orders'].c.customer_id==user['id'],lock=True)
    check(user['role']=='CUSTOMER' and o['status']=='DELIVERED','REVIEW_NOT_ALLOWED','Chỉ đánh giá đơn của bạn đã giao thành công',403)
    target=body.get('target','PRODUCT');check(target in ('PRODUCT','COURIER'),'INVALID_REVIEW','Chọn sản phẩm hoặc người giao')
    rating=number(body.get('rating'),places=0,minimum=Decimal(1),maximum=Decimal(5))
    product_id=courier_id=None
    if target=='COURIER':
        check(o['courier_id'],'NO_COURIER','Đơn không có người giao');courier_id=o['courier_id'];key='courier:'+courier_id
    else:
        item=await one(s,'order_items',T['order_items'].c.id==uuid(body.get('itemId')),T['order_items'].c.order_id==order_id)
        offer=await one(s,'offers',T['offers'].c.id==item['offer_id']);product_id=offer['product_id'];key='item:'+item['id']
    old=await one(s,'reviews',T['reviews'].c.order_id==order_id,T['reviews'].c.target_key==key,required=False)
    check(not old,'ALREADY_REVIEWED','Bạn đã đánh giá mục này',409)
    from .moderation import sanitize
    row=await add(s,'reviews',id=uid(),order_id=order_id,customer_id=user['id'],target_key=key,product_id=product_id,courier_id=courier_id,
                  rating=int(rating),comment=await sanitize(s,user,text(body.get('comment',''),1000),'review.comment',order_id),hidden=False,created_at=now())
    from .marketplace import shop_topic
    emit(s,'admin:ops','REVIEW_CREATED',{'id':row['id']});emit(s,shop_topic(o['shop_id']),'REVIEW_CREATED',{'id':row['id']})
    return public(row)


async def finance(s,user,query):
    auth.require_admin(user)
    from .menus import today,bounds
    try:
        start=date.fromisoformat(query.get('from',str(today())))
        end=date.fromisoformat(query.get('to',str(today())))
    except (ValueError,TypeError):check(False,'INVALID_DATE','Ngày tài chính không hợp lệ')
    check(start<=end and (end-start).days<=366,'INVALID_DATE','Khoảng ngày tối đa 367 ngày')
    t=T['money_entries'];conditions=[t.c.created_at>=bounds(start)[0],t.c.created_at<bounds(end)[1]]
    amounts=dict((await s.execute(select(t.c.kind,func.sum(t.c.amount)).where(*conditions).group_by(t.c.kind))).all())
    held=(await s.execute(select(func.coalesce(func.sum(t.c.amount),0)).where(t.c.method=='COD',t.c.remitted_at.is_(None)))).scalar_one()
    data=await rows(s,'money_entries',*conditions,limit=200,order=[t.c.created_at.desc(),t.c.id.desc()])
    refunds=await rows(s,'refund_requests',T['refund_requests'].c.state=='PENDING',limit=200)
    unremitted=await rows(s,'money_entries',t.c.method=='COD',t.c.remitted_at.is_(None),limit=200,order=t.c.created_at)
    from .analytics import daily_records
    records=list((await daily_records(s,[start+timedelta(days=n) for n in range((end-start).days+1)])).values())
    sales={k:sum(r[k] for r in records) for k in ('orders','merchandise','shipping','vat','missingCostLines','legacyPaymentOrders')}
    sales['cost']=None if sales['missingCostLines'] else sum(r['cost'] for r in records)
    sales['grossProfit']=None if sales['cost'] is None else sales['merchandise']-sales['cost']
    ids={e['collector_id'] for e in unremitted if e['collector_id']}
    people=dict((await s.execute(select(T['users'].c.id,T['users'].c.display_name).where(T['users'].c.id.in_(ids)))).all()) if ids else {}
    for entry in unremitted:entry['collector_name']=people.get(entry['collector_id'],'Nhân viên')
    return public({'from':start,'to':end,'received':amounts.get('PAYMENT',0),'refunded':amounts.get('REFUND',0),
                   'netCash':amounts.get('PAYMENT',0)-amounts.get('REFUND',0),'courierHolding':held,
                   'entries':data,'refunds':refunds,'unremitted':unremitted,'listLimit':200,'sales':sales})


async def refund(s,user,id,body):
    auth.require_admin(user)
    request=await one(s,'refund_requests',T['refund_requests'].c.id==id)
    o=await one(s,'orders',T['orders'].c.id==request['order_id'],lock=True)
    request=await one(s,'refund_requests',T['refund_requests'].c.id==id,lock=True)
    if request['state']=='COMPLETED':return public(request)
    reference=text(body.get('reference'),100,1); amount=number(body.get('amount'),places=0,minimum=Decimal(1),maximum=Decimal('999999999999999999'))
    check(amount==request['amount'],'REFUND_AMOUNT_MISMATCH','Phải hoàn đúng số tiền yêu cầu',409)
    await add(s,'money_entries',id=uid(),order_id=o['id'],kind='REFUND',method='BANK_REFUND',amount=amount,
              provider_ref='refund:'+reference,actor_id=user['id'],note=text(body.get('note',''),500),created_at=now())
    await change(s,'refund_requests',id,state='COMPLETED',reference=reference,completed_by=user['id'],completed_at=now(),note=text(body.get('note',''),500))
    paid,returned=await payments.balance(s,o['id'])
    state='REFUNDED' if returned>=paid else 'PAID' if paid-returned>=o['total'] else 'UNPAID'
    await change(s,'orders',o['id'],payment_status=state,version=o['version']+1,updated_at=now());o.update(payment_status=state,version=o['version']+1)
    await payments.changed(s,o);await commerce.audit(s,user,'payment.refund','order',o['id'],None,{'amount':amount,'reference':reference})
    await notify(s,o['customer_id'],'REFUND_COMPLETED',{'id':o['id'],'message':'Quản trị đã xác nhận hoàn tiền. Kiểm tra tài khoản nhận tiền.'})
    return public(await one(s,'refund_requests',T['refund_requests'].c.id==id))
