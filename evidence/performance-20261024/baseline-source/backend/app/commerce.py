"""Domain operations. Call within a transaction; flush_events before committing."""
from datetime import timedelta, datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select, func, and_, update
from sqlalchemy.dialects.mysql import insert
from .db import T, now, uid, uuid, one, rows, add, change, check, text, number, digest, public
from .auth import require_admin
from .events import emit, notify
from .moderation import sanitize

async def audit(s, user, action, entity, id, before=None, after=None):
    await add(s, 'audit_logs', id=uid(), actor_id=user['id'], action=action, entity_type=entity,
              entity_id=id, before_data=public(before) if before else None,
              after_data=public(after) if after else None, request_id=s.info.get('request_id', uid()), created_at=now())

def version(row, body):
    check(str(row['version']) == str(body.get('expectedVersion')), 'VERSION_CONFLICT',
          'Dữ liệu đã thay đổi. Vui lòng tải lại trước khi thao tác.', 409, {'currentVersion': str(row['version'])})

async def idem(s, user, scope, key, body):
    key = uuid(key)
    t = T['idempotency_keys']
    await s.execute(insert(t).values(actor_id=user['id'], scope=scope, key_uuid=key, request_hash=digest(body),
        state='IN_PROGRESS', created_at=now(), expires_at=now()+timedelta(days=7))
        .on_duplicate_key_update(key_uuid=key))
    item = (await s.execute(select(t).where(t.c.actor_id == user['id'], t.c.scope == scope, t.c.key_uuid == key)
                            .with_for_update())).mappings().one()
    check(item['request_hash'] == digest(body), 'IDEMPOTENCY_CONFLICT', 'Mã thao tác đã dùng với dữ liệu khác', 409)
    return item['response_body'] if item['state'] == 'COMPLETED' else None

async def complete(s, user, scope, key, response):
    t = T['idempotency_keys']
    await s.execute(update(t).where(t.c.actor_id == user['id'], t.c.scope == scope, t.c.key_uuid == uuid(key))
                    .values(state='COMPLETED', http_status=200, response_body=public(response)))
    return response

async def lock_user(s, id): return await one(s, 'users', T['users'].c.id == id, lock=True)

async def catalog(s, user, admin=False, offer_ids=None):
    o, p, u, price = T['offers'], T['products'], T['units'], T['offer_prices']
    q = select(o, p.c.name, p.c.sku, p.c.description, p.c.quantity_step, p.c.category_id,
               u.c.label.label('unit'), price.c.unit_price, price.c.version.label('price_version')).join(p, o.c.product_id==p.c.id)\
        .join(u, p.c.unit_id==u.c.id).outerjoin(price, and_(price.c.offer_id==o.c.id, price.c.group_id==user['group_id']))
    if not admin: q = q.where(o.c.status=='OPEN', p.c.active==True, p.c.deleted_at==None,
                              o.c.opens_at <= now(), o.c.closes_at > now(), price.c.unit_price != None)
    if offer_ids is not None: q=q.where(o.c.id.in_(offer_ids))
    offers = [dict(r) for r in (await s.execute(q.order_by(o.c.sale_date.desc(), p.c.name).limit(200))).mappings()]
    i, order = T['order_items'], T['orders']
    counts = (await s.execute(select(i.c.offer_id, order.c.status, func.sum(i.c.quantity).label('qty'),
            func.count(func.distinct(order.c.customer_id)).label('customers'), func.count().label('orders'))
            .join(order, i.c.order_id==order.c.id).where(i.c.offer_id.in_([o['id'] for o in offers]))
            .group_by(i.c.offer_id, order.c.status))).mappings().all() if offers else []
    images = await rows(s, 'product_images', limit=1000)
    subscriptions = await rows(s, 'product_subscriptions', T['product_subscriptions'].c.user_id==user['id'], limit=500)
    followed = {r['product_id'] for r in subscriptions}
    for offer in offers:
        count = [c for c in counts if c['offer_id']==offer['id']]
        offer['pending_qty'] = sum((c['qty'] for c in count if c['status']=='PENDING'), Decimal(0))
        offer['pending_customers'] = sum(c['customers'] for c in count if c['status']=='PENDING')
        offer['approved_orders'] = sum(c['orders'] for c in count if c['status'] in ('APPROVED','PREPARING','SHIPPING','DELIVERED'))
        offer['images'] = [x['asset_id'] for x in sorted(images, key=lambda x: x['position']) if x['product_id']==offer['product_id']]
        offer['subscribed'] = offer['product_id'] in followed
        if admin: offer['prices'] = await rows(s, 'offer_prices', price.c.offer_id==offer['id'])
    return public(offers)

async def catalog_event(s, ids):
    # Each price group gets only its own canonical deltas, avoiding a GET storm.
    import json
    for group in await rows(s, 'customer_groups', T['customer_groups'].c.active==True):
        if not ids:
            emit(s,'catalog:'+group['id'],'CATALOG_CHANGED',{'refresh':True})
            continue
        offers=await catalog(s,{'id':'00000000-0000-0000-0000-000000000000','group_id':group['id']},offer_ids=ids)
        for offer in offers: offer.pop('subscribed',None)
        missing=sorted(set(ids)-{o['id'] for o in offers})
        batch=[]
        for offer in offers:
            if batch and len(json.dumps(batch+[offer],ensure_ascii=False).encode())>28000:
                emit(s,'catalog:'+group['id'],'CATALOG_CHANGED',{'offers':batch,'removedOfferIds':[]});batch=[]
            batch.append(offer)
        emit(s,'catalog:'+group['id'],'CATALOG_CHANGED',{'offers':batch,'removedOfferIds':missing})
    emit(s, 'admin:ops', 'CATALOG_CHANGED', {'offerIds': sorted(set(ids))})

async def get_order(s, user, id):
    order = await one(s, 'orders', T['orders'].c.id==id)
    check(user['role']=='ADMIN' or order['customer_id']==user['id'], 'FORBIDDEN', 'Không có quyền xem đơn', 403)
    order.pop('request_hash', None)
    order['items'] = await rows(s, 'order_items', T['order_items'].c.order_id==id)
    order['history'] = await rows(s, 'order_status_history', T['order_status_history'].c.order_id==id,
                                 order=T['order_status_history'].c.order_version)
    order['cancellation_requests'] = await rows(s, 'cancellation_requests', T['cancellation_requests'].c.order_id==id)
    return public(order)

async def delivery(s, user, body, subtotal):
    address = await one(s, 'addresses', T['addresses'].c.id==uuid(body.get('addressId')),
                        T['addresses'].c.user_id==user['id'], T['addresses'].c.deleted_at==None)
    method = body.get('deliveryMethod', 'INDIVIDUAL')
    check(method in ('COLLECTIVE','INDIVIDUAL'), 'INVALID_DELIVERY', 'Cách giao không hợp lệ')
    policy = await one(s, 'delivery_policies', T['delivery_policies'].c.group_id==user['group_id'],
        T['delivery_policies'].c.zone_id==address['zone_id'], T['delivery_policies'].c.method==method,
        T['delivery_policies'].c.active==True, lock=True)
    check(str(policy['version'])==str(body.get('policyVersion')), 'REQUOTE_REQUIRED', 'Phí hoặc điều kiện giao đã thay đổi', 409)
    check(subtotal>=policy['minimum_subtotal'], 'DELIVERY_MINIMUM', 'Đơn chưa đạt mức tối thiểu cho cách giao này')
    snapshot = {'policyId':policy['id'], 'policyVersion':str(policy['version']), 'zoneId':policy['zone_id'], 'method':method,
                'shippingFee':str(policy['shipping_fee']), 'minimumSubtotal':str(policy['minimum_subtotal'])}
    if method=='COLLECTIVE':
        group = await one(s, 'customer_groups', T['customer_groups'].c.id==user['group_id'])
        check(group['code']=='STUDENT' and policy['shipping_fee']==0, 'INVALID_DELIVERY', 'Giao tập trung chỉ dành cho sinh viên và miễn phí')
        slot = await one(s, 'pickup_slots', T['pickup_slots'].c.id==uuid(body.get('pickupSlotId')),
                         T['pickup_slots'].c.zone_id==address['zone_id'], T['pickup_slots'].c.active==True, lock=True)
        check(slot['ends_at']>now(), 'PICKUP_EXPIRED', 'Khung giao đã hết hạn')
        check(str(slot['version'])==str(body.get('pickupSlotVersion')), 'REQUOTE_REQUIRED', 'Điểm hoặc lịch giao đã thay đổi',409)
        snapshot['pickupSlot']=public(slot)
    return address, policy, snapshot

async def create_order(s, user, body, key, quote=None):
    scope='create-order'
    prior=await idem(s,user,scope,key,body)
    if prior: return prior
    user=await lock_user(s,user['id'])
    clientid=uuid(body.get('clientOrderId'))
    old=await one(s,'orders',T['orders'].c.customer_id==user['id'],T['orders'].c.client_order_id==clientid,required=False)
    if old:
        check(old['request_hash']==digest(body),'IDEMPOTENCY_CONFLICT','Mã đơn đã dùng cho nội dung khác',409)
        return await complete(s,user,scope,key,await get_order(s,user,old['id']))
    lines=body.get('items',[])
    check(isinstance(lines,list) and 1<=len(lines)<=20 and all(isinstance(line,dict) for line in lines),
          'INVALID_ITEMS','Đơn cần từ 1 đến 20 mặt hàng hợp lệ')
    ids=[uuid(line.get('offerId')) for line in lines]
    check(len(set(ids))==len(ids),'DUPLICATE_ITEM','Mỗi mặt hàng chỉ xuất hiện một lần')
    locked={id:await one(s,'offers',T['offers'].c.id==id,lock=True) for id in sorted(ids)}
    items=[]
    for line,id in zip(lines,ids):
        offer=locked[id]
        check(offer['status']=='OPEN' and offer['opens_at']<=now()<offer['closes_at'] and not offer['processing_locked_at'],
              'OFFER_CLOSED','Đợt bán đã đóng',409)
        product=await one(s,'products',T['products'].c.id==offer['product_id'])
        check(product['active'] and not product['deleted_at'],'PRODUCT_UNAVAILABLE','Mặt hàng không còn bán',409)
        qty=number(line.get('quantity'),minimum=Decimal('.001'))
        check(qty % product['quantity_step']==0,'INVALID_STEP','Số lượng không đúng bước đơn vị')
        check(qty<=offer['available_qty'],'INSUFFICIENT_STOCK','Lượng trong kho không đủ',409)
        price=await one(s,'offer_prices',T['offer_prices'].c.offer_id==id,T['offer_prices'].c.group_id==user['group_id'])
        if quote:
            check(id==quote['offer_id'] and qty==quote['quantity'],'QUOTE_MISMATCH','Nội dung không đúng báo giá')
            unitprice=quote['unit_price']
        else:
            check(str(price['version'])==str(line.get('expectedPriceVersion')),'REQUOTE_REQUIRED','Giá đã thay đổi, vui lòng kiểm tra lại',409)
            unitprice=price['unit_price']
        unit=await one(s,'units',T['units'].c.id==product['unit_id'])
        quoted_item=(quote.get('item_snapshot') or {}) if quote else {}
        items.append(dict(id=uid(),offer_id=id,product_name_snapshot=quoted_item.get('productName',product['name']),unit_snapshot=quoted_item.get('unitLabel',unit['label']),
                          quantity=qty,unit_price=unitprice,price_version=price['version'],
                          line_total=(unitprice*qty).quantize(Decimal('1'),rounding=ROUND_HALF_UP)))
    subtotal=sum(i['line_total'] for i in items)
    if quote:
        # A valid accepted quote freezes the fee and delivery terms just as it freezes price.
        address=await one(s,'addresses',T['addresses'].c.id==uuid(body.get('addressId')),
                          T['addresses'].c.user_id==user['id'],T['addresses'].c.deleted_at==None)
        shipping=quote['delivery_snapshot'];fee=quote['shipping_fee']
        policy=await one(s,'delivery_policies',T['delivery_policies'].c.id==shipping['policyId'],lock=True)
        check(address['zone_id']==policy['zone_id'] and body.get('deliveryMethod')==shipping['method'],
              'REQUOTE_REQUIRED','Chọn đúng khu vực và cách giao đã thỏa thuận trong báo giá',409)
        check(subtotal>=Decimal(shipping['minimumSubtotal']),'DELIVERY_MINIMUM','Chưa đủ điều kiện đã báo giá')
        if shipping['method']=='COLLECTIVE':
            group=await one(s,'customer_groups',T['customer_groups'].c.id==user['group_id'])
            check(group['code']=='STUDENT','INVALID_DELIVERY','Giao tập trung chỉ dành cho nhóm sinh viên')
            slot=shipping.get('pickupSlot',{})
            ends_at=datetime.fromisoformat(slot['ends_at'].replace('Z','+00:00')).replace(tzinfo=None)
            check(slot.get('id')==body.get('pickupSlotId') and ends_at>now(),
                  'PICKUP_EXPIRED','Điểm hoặc thời gian nhận không đúng báo giá')
    else:
        address,policy,shipping=await delivery(s,user,body,subtotal)
        fee=policy['shipping_fee']
    check(subtotal+fee<=Decimal('999999999999999999'),'ORDER_TOO_LARGE','Tổng đơn vượt giới hạn xử lý')
    group=await one(s,'customer_groups',T['customer_groups'].c.id==user['group_id'])
    id=uid()
    await add(s,'orders',id=id,customer_id=user['id'],client_order_id=clientid,request_hash=digest(body),status='PENDING',
              group_snapshot={'id':group['id'],'code':group['code'],'name':group['name']},address_snapshot=public(address),
              delivery_snapshot=shipping,delivery_method=shipping['method'],merchandise_total=subtotal,shipping_fee=fee,
              total=subtotal+fee,version=1,created_at=now(),updated_at=now(),
              source_request_id=quote['request_id'] if quote else None,source_quote_id=quote['id'] if quote else None,
              note=await sanitize(s,user,text(body.get('note',''),1000),'order.note',id))
    for item in items: await add(s,'order_items',order_id=id,**item)
    await add(s,'order_status_history',id=uid(),order_id=id,actor_id=user['id'],from_status=None,to_status='PENDING',order_version=1,created_at=now())
    result=await get_order(s,user,id)
    emit(s,'user:'+user['id'],'ORDER_CHANGED',{'id':id,'status':'PENDING','version':'1'},id,1)
    emit(s,'admin:ops','ORDER_CHANGED',{'id':id,'status':'PENDING','version':'1'},id,1)
    await notify(s,user['id'],'ORDER_CREATED',{'id':id,'message':'Đơn đã gửi, đang chờ duyệt; chưa giữ hàng.'})
    await catalog_event(s,ids)
    return await complete(s,user,scope,key,result)

async def order_action(s,user,id,action,body,key):
    scope='order:'+id+':'+action
    prior=await idem(s,user,scope,key,body)
    if prior: return prior
    initial=await one(s,'orders',T['orders'].c.id==id)
    await lock_user(s,initial['customer_id'])
    order=await one(s,'orders',T['orders'].c.id==id,lock=True)
    if user['role']!='ADMIN':
        check(order['customer_id']==user['id'] and action in ('cancel','request-cancel'),'FORBIDDEN','Không có quyền xử lý đơn',403)
    else: require_admin(user)
    version(order,body)
    items=await rows(s,'order_items',T['order_items'].c.order_id==id)
    offers={i:await one(s,'offers',T['offers'].c.id==i,lock=True) for i in sorted(x['offer_id'] for x in items)}
    status=order['status']
    reason=await sanitize(s,user,text(body.get('reason',''),1000),'order.reason',id)
    values={}
    if action=='approve':
        require_admin(user)
        check(status=='PENDING','INVALID_STATE','Chỉ duyệt đơn đang chờ',409)
        check(all(not offers[i['offer_id']]['processing_locked_at'] and offers[i['offer_id']]['available_qty']>=i['quantity'] for i in items),
              'INSUFFICIENT_STOCK','Không đủ kho để duyệt toàn bộ đơn',409)
        for item in items: await move_stock(s,user,offers[item['offer_id']],-item['quantity'],'APPROVE',id,id)
        target='APPROVED'; values['approved_at']=now()
    elif action in ('cancel','reject'):
        if action=='reject': require_admin(user)
        check(status=='PENDING','INVALID_STATE','Đơn đã duyệt cần gửi yêu cầu hủy',409)
        target='REJECTED' if action=='reject' else 'CANCELLED'
        if target=='CANCELLED': values['cancelled_at']=now()
    elif action=='request-cancel':
        check(status in ('APPROVED','PREPARING'),'INVALID_STATE','Chỉ yêu cầu hủy trước khi bàn giao vận chuyển',409)
        check(bool(reason),'REASON_REQUIRED','Vui lòng nhập lý do hủy')
        open_request=await one(s,'cancellation_requests',T['cancellation_requests'].c.order_id==id,T['cancellation_requests'].c.state=='OPEN',required=False)
        check(not open_request,'CANCELLATION_OPEN','Đơn đã có yêu cầu hủy',409)
        await add(s,'cancellation_requests',id=uid(),order_id=id,requested_by=user['id'],reason=reason,state='OPEN',version=1,created_at=now())
        # Bump the aggregate version: a concurrent SHIPPING attempt must fail.
        target=status
    elif action=='decide-cancel':
        require_admin(user)
        check(isinstance(body.get('accept'),bool),'INVALID_BOOLEAN','Quyết định hủy phải là giá trị đúng/sai')
        cancellation=await one(s,'cancellation_requests',T['cancellation_requests'].c.order_id==id,
                               T['cancellation_requests'].c.state=='OPEN',lock=True)
        check(status in ('APPROVED','PREPARING'),'INVALID_STATE','Không thể hủy sau bàn giao',409)
        accept=body.get('accept') is True
        await change(s,'cancellation_requests',cancellation['id'],state='ACCEPTED' if accept else 'REJECTED',
                     decision_by=user['id'],decision_note=reason,decided_at=now(),version=cancellation['version']+1)
        target='CANCELLED' if accept else status
        if accept:
            for item in items: await move_stock(s,user,offers[item['offer_id']],item['quantity'],'CANCEL_RESTORE',id,id)
            values['cancelled_at']=now()
    elif action=='transition':
        require_admin(user)
        target=body.get('status')
        check({'APPROVED':'PREPARING','PREPARING':'SHIPPING','SHIPPING':'DELIVERED'}.get(status)==target,
              'INVALID_STATE','Không thể chuyển sang trạng thái này',409)
        if target=='SHIPPING':
            pending=await one(s,'cancellation_requests',T['cancellation_requests'].c.order_id==id,T['cancellation_requests'].c.state=='OPEN',required=False)
            check(not pending,'CANCELLATION_OPEN','Cần xử lý yêu cầu hủy trước khi giao',409)
            values['shipped_at']=now()
        if target=='DELIVERED': values['delivered_at']=now()
    else: check(False,'UNKNOWN_ACTION','Thao tác không hợp lệ')
    await change(s,'orders',id,status=target,version=order['version']+1,updated_at=now(),**values)
    await add(s,'order_status_history',id=uid(),order_id=id,actor_id=user['id'],from_status=status,to_status=target,
              order_version=order['version']+1,reason=reason,created_at=now())
    result=await get_order(s,user,id)
    await audit(s,user,'order.'+action,'order',id,{'status':status},{'status':target})
    for topic in ('user:'+order['customer_id'],'admin:ops'):
        emit(s,topic,'ORDER_CHANGED',{'id':id,'status':target,'version':str(order['version']+1)},id,order['version']+1)
    await notify(s,order['customer_id'],'ORDER_STATUS',{'id':id,'status':target,'message':'Đơn hàng vừa được cập nhật.'})
    await catalog_event(s,list(offers))
    return await complete(s,user,scope,key,result)

async def move_stock(s,user,offer,delta,kind,reference,order_id=None,reason=None):
    balance=offer['available_qty']+delta
    check(balance>=0,'INSUFFICIENT_STOCK','Tồn kho không đủ',409)
    await change(s,'offers',offer['id'],available_qty=balance,version=offer['version']+1,updated_at=now())
    await add(s,'inventory_movements',id=uid(),offer_id=offer['id'],actor_id=user['id'],kind=kind,
              reference_id=reference,order_id=order_id,quantity_delta=delta,balance_after=balance,reason=reason,created_at=now())
