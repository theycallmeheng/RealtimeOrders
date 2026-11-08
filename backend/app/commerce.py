"""Domain operations. Call within a transaction; flush_events before committing."""
from datetime import timedelta, datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select, func, and_, update
from sqlalchemy.dialects.mysql import insert
from .db import T, now, uid, uuid, one, rows, add, change, check, text, number, digest, public
from .auth import require_shop as require_admin, is_shop
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

async def catalog(s, user, admin=False, offer_ids=None, menu_id=None, shop_id=None):
    from .marketplace import scope
    from .menus import audience
    o, p, u, price, groups = T['offers'], T['products'], T['units'], T['offer_prices'], T['customer_groups']
    categories, shops = T['categories'], T['shops']
    q = select(o, shops.c.name.label('shop_name'), p.c.name, p.c.sku, p.c.description, p.c.quantity_step, p.c.category_id,
               categories.c.name.label('category_name'),
               p.c.allowed_group_ids.label('product_allowed_group_ids'),
               u.c.label.label('unit'), price.c.unit_price, price.c.version.label('price_version')).join(p, o.c.product_id==p.c.id)\
        .join(u, p.c.unit_id==u.c.id).join(shops, o.c.shop_id==shops.c.id).outerjoin(categories, p.c.category_id==categories.c.id)\
        .outerjoin(price, and_(price.c.offer_id==o.c.id, price.c.group_id==user['group_id']))
    if admin:
        q = q.where(o.c.archived_at.is_(None), *scope(o, user, shop_id))
    elif shop_id:
        q = q.where(o.c.shop_id == uuid(shop_id))
    if not admin:
        m=T['daily_menus']
        q=q.join(m,o.c.menu_id==m.c.id).join(groups,groups.c.id==price.c.group_id).where(o.c.status=='OPEN',o.c.archived_at==None,
            p.c.active==True,p.c.deleted_at==None,groups.c.active==True,shops.c.active.is_(True),
            m.c.status=='OPEN',m.c.opens_at<=now(),m.c.closes_at>now(),price.c.unit_price!=None,
            audience(p.c.allowed_group_ids,user['group_id']),audience(o.c.allowed_group_ids,user['group_id']),
            audience(m.c.allowed_group_ids,user['group_id']))
    if offer_ids is not None: q=q.where(o.c.id.in_(offer_ids))
    if menu_id is not None: q=q.where(o.c.menu_id==menu_id)
    offers = [dict(r) for r in (await s.execute(q.order_by(o.c.sale_date.desc(), p.c.name).limit(200))).mappings()]
    if not offers: return []
    offer_ids=[offer['id'] for offer in offers]
    product_ids=sorted({offer['product_id'] for offer in offers})
    i, order = T['order_items'], T['orders']
    counts = (await s.execute(select(i.c.offer_id, order.c.status, func.sum(i.c.quantity).label('qty'),
            func.count(func.distinct(order.c.customer_id)).label('customers'), func.count().label('orders'))
            .join(order, i.c.order_id==order.c.id).where(i.c.offer_id.in_(offer_ids))
            .group_by(i.c.offer_id, order.c.status))).mappings().all()
    images = await rows(s, 'product_images', T['product_images'].c.product_id.in_(product_ids),
                        limit=1000, order=T['product_images'].c.position)
    subscriptions = await rows(s, 'product_subscriptions', T['product_subscriptions'].c.user_id==user['id'], limit=500)
    followed = {r['product_id'] for r in subscriptions}
    counts_by_offer={}
    for count in counts: counts_by_offer.setdefault(count['offer_id'],[]).append(count)
    images_by_product={}
    for image in images:
        source=image['asset_id'] or image['source_url']
        if source: images_by_product.setdefault(image['product_id'],[]).append(source)
    prices_by_offer={}
    if admin:
        for row in (await s.execute(select(price).where(price.c.offer_id.in_(offer_ids)))).mappings():
            prices_by_offer.setdefault(row['offer_id'],[]).append(dict(row))
    for offer in offers:
        count = counts_by_offer.get(offer['id'],[])
        offer['pending_qty'] = sum((c['qty'] for c in count if c['status']=='PENDING'), Decimal(0))
        offer['pending_customers'] = sum(c['customers'] for c in count if c['status']=='PENDING')
        offer['approved_orders'] = sum(c['orders'] for c in count if c['status'] in ('APPROVED','PREPARING','SHIPPING','DELIVERED'))
        offer['images'] = images_by_product.get(offer['product_id'],[])
        offer['subscribed'] = offer['product_id'] in followed
        if admin: offer['prices'] = prices_by_offer.get(offer['id'],[])[:100]
        else:
            for key in ('cost_price','sale_price_override','batch_code','archived_at','allowed_group_ids','product_allowed_group_ids'): offer.pop(key,None)
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

def can_read_order(user, order):
    if user['role'] == 'ADMIN':
        return True
    if user['role'] == 'SELLER':
        return user.get('shop_id') == order['shop_id']
    if user['role'] == 'SHIPPER':
        return order.get('courier_id') == user['id']
    return order['customer_id'] == user['id']


async def get_order(s, user, id):
    order = await one(s, 'orders', T['orders'].c.id==id)
    check(can_read_order(user, order), 'FORBIDDEN', 'Không có quyền xem đơn', 403)
    order.pop('request_hash', None)
    order['items'] = await rows(s, 'order_items', T['order_items'].c.order_id==id)
    if not is_shop(user):
        order.pop('platform_fee',None)
        order.pop('platform_fee_rate',None)
        for item in order['items']: item.pop('cost_price_snapshot',None)
    from .payments import summary
    order['payment'] = public(await summary(s,order))
    order['history'] = await rows(s, 'order_status_history', T['order_status_history'].c.order_id==id,
                                 order=T['order_status_history'].c.order_version)
    order['cancellation_requests'] = await rows(s, 'cancellation_requests', T['cancellation_requests'].c.order_id==id)
    return public(order)

async def get_orders(s,user,ids):
    """Load authorized snapshot orders with a fixed number of child queries."""
    if not ids: return []
    t,money=T['orders'],T['money_entries']
    totals=select(money.c.order_id,func.sum(func.if_(money.c.kind=='PAYMENT',money.c.amount,0)).label('_received'),
                  func.sum(func.if_(money.c.kind=='REFUND',money.c.amount,0)).label('_refunded')).where(money.c.order_id.in_(ids)).group_by(money.c.order_id).subquery()
    query=select(t,totals.c._received,totals.c._refunded).outerjoin(totals,t.c.id==totals.c.order_id).where(t.c.id.in_(ids))
    orders=[dict(row) for row in (await s.execute(query)).mappings()]
    for o in orders:
        paid=o.pop('_received') or Decimal(0);refunded=o.pop('_refunded') or Decimal(0)
        o['payment']={'received':paid,'refunded':refunded,'remaining':Decimal(0) if o['status'] in ('CANCELLED','REJECTED') else max(Decimal(0),o['total']-paid+refunded),'tracked':o['payment_method']!='LEGACY'}
    by_id={order['id']:order for order in orders}
    check(all(id in by_id for id in ids),'NOT_FOUND','Không tìm thấy dữ liệu',404)
    check(all(can_read_order(user, order) for order in orders),
          'FORBIDDEN','Không có quyền xem đơn',403)
    for order in orders:
        order.pop('request_hash',None)
        if not is_shop(user):
            order.pop('platform_fee',None)
            order.pop('platform_fee_rate',None)
        order.update(items=[],history=[],cancellation_requests=[])
    for table,key in (('order_items','items'),('order_status_history','history'),('cancellation_requests','cancellation_requests')):
        query=select(T[table]).where(T[table].c.order_id.in_(ids))
        if key=='history':query=query.order_by(T[table].c.order_version)
        for row in (await s.execute(query)).mappings():
            row=dict(row)
            if not is_shop(user): row.pop('cost_price_snapshot',None)
            values=by_id[row['order_id']][key]
            if len(values)<100: values.append(dict(row))
    return public([by_id[id] for id in ids])

async def delivery(s, user, body, subtotal, shop_id=None):
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
    else:
        from .shipping import validate_quote
        check(body.get('deliveryQuoteId'),'REQUOTE_REQUIRED','Lấy phí giao và xác nhận trước khi đặt đơn',409)
        quote=await validate_quote(s,user,body,address,policy,shop_id)
        snapshot.update(shippingFee=str(quote['shipping_fee']),distanceMeters=quote['distance_meters'],
            durationSeconds=quote['duration_seconds'],deliveryQuoteId=quote['id'])
    return address, policy, snapshot

async def create_order(s, user, body, key):
    check(user['role']=='CUSTOMER','FORBIDDEN','Chỉ khách hàng được đặt đơn',403)
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
    # Match the menu editor's lock order: menu before offers.
    menu_ids=(await s.execute(select(T['offers'].c.menu_id).where(T['offers'].c.id.in_(ids)))).scalars().all()
    for menu_id in sorted({m for m in menu_ids if m}):
        await one(s,'daily_menus',T['daily_menus'].c.id==menu_id,lock=True)
    locked={id:await one(s,'offers',T['offers'].c.id==id,lock=True) for id in sorted(ids)}
    from .marketplace import get_shop, order_fee, shop_topic
    shops = {offer['shop_id'] for offer in locked.values()}
    check(len(shops) == 1, 'MIXED_SHOPS', 'Mỗi đơn chỉ đặt món của một shop', 409)
    shop_id = shops.pop()
    shop = await get_shop(s, shop_id, active=True)
    items=[]
    for line,id in zip(lines,ids):
        offer=locked[id]
        check(offer['status']=='OPEN' and offer['opens_at']<=now()<offer['closes_at'] and not offer['processing_locked_at'],
              'OFFER_CLOSED','Đợt bán đã đóng',409)
        product=await one(s,'products',T['products'].c.id==offer['product_id'])
        from .menus import visible
        check(await visible(s,user,offer,product),'PRODUCT_UNAVAILABLE','Mặt hàng không còn được phép mua hoặc menu đã đóng',409)
        check(product['active'] and not product['deleted_at'],'PRODUCT_UNAVAILABLE','Mặt hàng không còn bán',409)
        qty=number(line.get('quantity'),minimum=Decimal('.001'))
        check(qty % product['quantity_step']==0,'INVALID_STEP','Số lượng không đúng bước đơn vị')
        check(offer['available_qty']>0,'SOLD_OUT','Mặt hàng đã bán hết. Vui lòng chờ bổ sung kho.',409)
        check(qty<=offer['available_qty'],'INSUFFICIENT_STOCK','Lượng trong kho không đủ',409)
        price=await one(s,'offer_prices',T['offer_prices'].c.offer_id==id,T['offer_prices'].c.group_id==user['group_id'])
        check(str(price['version'])==str(line.get('expectedPriceVersion')),'REQUOTE_REQUIRED','Giá đã thay đổi, vui lòng kiểm tra lại',409)
        unitprice=price['unit_price']
        unit=await one(s,'units',T['units'].c.id==product['unit_id'])
        items.append(dict(id=uid(),offer_id=id,product_name_snapshot=product['name'],unit_snapshot=unit['label'],
                          quantity=qty,unit_price=unitprice,price_version=price['version'],
                          line_total=(unitprice*qty).quantize(Decimal('1'),rounding=ROUND_HALF_UP)))
    subtotal=sum(i['line_total'] for i in items)
    address,policy,shipping=await delivery(s,user,body,subtotal,shop_id)
    platform_rate, platform_fee = await order_fee(s, subtotal)
    fee=Decimal(shipping['shippingFee'])
    from .payments import vat_policy,tax,configured
    policy_data,policy_version=await vat_policy(s)
    vat_rate=number(policy_data['rate'],places=2,maximum=Decimal(100));vat_amount=tax(subtotal,vat_rate)
    check(str(body.get('vatVersion',policy_version if vat_rate==0 else ''))==str(policy_version),'REQUOTE_REQUIRED','Thuế đã thay đổi; kiểm tra lại tổng tiền',409)
    method=body.get('paymentMethod','COD')
    check(method in ('COD','PAYOS'),'INVALID_PAYMENT','Chọn COD hoặc payOS')
    check(method!='PAYOS' or configured(),'PAYMENT_NOT_CONFIGURED','payOS chưa được cấu hình',503)
    check(subtotal+fee+vat_amount<=Decimal('999999999999999999'),'ORDER_TOO_LARGE','Tổng đơn vượt giới hạn xử lý')
    group=await one(s,'customer_groups',T['customer_groups'].c.id==user['group_id'])
    id=uid()
    await add(s,'orders',id=id,customer_id=user['id'],shop_id=shop_id,shop_name_snapshot=shop['name'],
              platform_fee_rate=platform_rate,platform_fee=platform_fee,client_order_id=clientid,request_hash=digest(body),status='PENDING',
              group_snapshot={'id':group['id'],'code':group['code'],'name':group['name']},address_snapshot=public(address),
              delivery_snapshot=shipping,delivery_method=shipping['method'],merchandise_total=subtotal,shipping_fee=fee,
              total=subtotal+fee+vat_amount,vat_rate=vat_rate,vat_amount=vat_amount,payment_method=method,payment_status='UNPAID',version=1,created_at=now(),updated_at=now(),
              note=await sanitize(s,user,text(body.get('note',''),1000),'order.note',id))
    for item in items: await add(s,'order_items',order_id=id,**item)
    await add(s,'order_status_history',id=uid(),order_id=id,actor_id=user['id'],from_status=None,to_status='PENDING',order_version=1,created_at=now())
    result=await get_order(s,user,id)
    emit(s,'user:'+user['id'],'ORDER_CHANGED',{'id':id,'status':'PENDING','version':'1'},id,1)
    emit(s,'admin:ops','ORDER_CHANGED',{'id':id,'status':'PENDING','version':'1'},id,1)
    emit(s,shop_topic(shop_id),'ORDER_CHANGED',{'id':id,'status':'PENDING','version':'1'},id,1)
    await notify(s,user['id'],'ORDER_CREATED',{'id':id,'message':'Đơn đã gửi, đang chờ duyệt; chưa giữ hàng.'})
    await catalog_event(s,ids)
    return await complete(s,user,scope,key,result)

async def order_action(s,user,id,action,body,key):
    scope='order:'+id+':'+action
    initial=await one(s,'orders',T['orders'].c.id==id)
    check(can_read_order(user, initial), 'FORBIDDEN', 'Không có quyền xử lý đơn', 403)
    prior=await idem(s,user,scope,key,body)
    if prior: return prior
    await lock_user(s,initial['customer_id'])
    order=await one(s,'orders',T['orders'].c.id==id,lock=True)
    courier=user['role']=='SHIPPER' and order.get('courier_id')==user['id']
    if courier:
        check(action=='transition','FORBIDDEN','Người giao chỉ được xử lý giao nhận',403)
    elif not is_shop(user):
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
        for item in items:
            offer=offers[item['offer_id']]
            check(not offer['menu_id'] or offer['cost_price'] is not None,'COST_REQUIRED','Cần nhập giá vốn trước khi duyệt')
            await change(s,'order_items',item['id'],cost_price_snapshot=offer['cost_price'])
            await move_stock(s,user,offer,-item['quantity'],'APPROVE',id,id)
        target='APPROVED'; values['approved_at']=now()
        if order['payment_method']=='PAYOS':
            from .config import settings
            values['payment_deadline']=now()+timedelta(seconds=settings.payment_ttl_seconds)
            if order['total']==0:values['payment_status']='PAID'
    elif action in ('cancel','reject'):
        if action=='reject': require_admin(user)
        check(status=='PENDING','INVALID_STATE','Đơn đã duyệt cần gửi yêu cầu hủy',409)
        target='REJECTED' if action=='reject' else 'CANCELLED'
        if target=='CANCELLED': values['cancelled_at']=now()
    elif action=='request-cancel':
        check(status in ('APPROVED','PREPARING','READY_FOR_PICKUP'),'INVALID_STATE','Chỉ yêu cầu hủy trước khi bàn giao vận chuyển',409)
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
        check(status in ('APPROVED','PREPARING','READY_FOR_PICKUP'),'INVALID_STATE','Không thể hủy sau bàn giao',409)
        accept=body.get('accept') is True
        await change(s,'cancellation_requests',cancellation['id'],state='ACCEPTED' if accept else 'REJECTED',
                     decision_by=user['id'],decision_note=reason,decided_at=now(),version=cancellation['version']+1)
        target='CANCELLED' if accept else status
        if accept:
            for item in items: await move_stock(s,user,offers[item['offer_id']],item['quantity'],'CANCEL_RESTORE',id,id)
            values['cancelled_at']=now()
    elif action=='transition':
        check(is_shop(user) or courier,'FORBIDDEN','Không có quyền giao nhận',403)
        target=body.get('status')
        next_state={'APPROVED':'PREPARING','PREPARING':'READY_FOR_PICKUP' if order['delivery_method']=='COLLECTIVE' else 'SHIPPING','SHIPPING':'DELIVERED','READY_FOR_PICKUP':'DELIVERED'}
        check(next_state.get(status)==target,
              'INVALID_STATE','Không thể chuyển sang trạng thái này',409)
        check(not courier or target=='DELIVERED','FORBIDDEN','Người bán điều phối các bước chuẩn bị và bàn giao',403)
        if order['payment_method']=='PAYOS':
            from .payments import balance
            paid,refunded=await balance(s,id)
            check(paid-refunded>=order['total'],'PAYMENT_REQUIRED','Cần thanh toán đủ trước khi chuẩn bị/giao hàng',409)
        if target in ('SHIPPING','READY_FOR_PICKUP'):
            check(order.get('courier_id'),'COURIER_REQUIRED','Phân công người giao/trao hàng trước',409)
            await one(s,'users',T['users'].c.id==order['courier_id'],T['users'].c.role=='SHIPPER',T['users'].c.status=='ACTIVE')
        if target in ('SHIPPING','READY_FOR_PICKUP','DELIVERED'):
            pending_cancel=await one(s,'cancellation_requests',T['cancellation_requests'].c.order_id==id,T['cancellation_requests'].c.state=='OPEN',required=False)
            check(not pending_cancel,'CANCELLATION_OPEN','Cần xử lý yêu cầu hủy trước khi bàn giao',409)
        if target=='SHIPPING':
            pending=await one(s,'cancellation_requests',T['cancellation_requests'].c.order_id==id,T['cancellation_requests'].c.state=='OPEN',required=False)
            check(not pending,'CANCELLATION_OPEN','Cần xử lý yêu cầu hủy trước khi giao',409)
            values['shipped_at']=now()
        if target=='DELIVERED':
            if order['payment_method']=='COD':
                check(number(body.get('codAmount'),places=0)==order['total'],'COD_AMOUNT_REQUIRED','Cần xác nhận đã thu đủ tiền COD',409)
                if order['total']>0:await add(s,'money_entries',id=uid(),order_id=id,kind='PAYMENT',method='COD',amount=order['total'],provider_ref='cod:'+id,actor_id=user['id'],collector_id=order.get('courier_id') or user['id'],created_at=now())
                values['payment_status']='PAID'
            values['delivered_at']=now()
    else: check(False,'UNKNOWN_ACTION','Thao tác không hợp lệ')
    await change(s,'orders',id,status=target,version=order['version']+1,updated_at=now(),**values)
    await add(s,'order_status_history',id=uid(),order_id=id,actor_id=user['id'],from_status=status,to_status=target,
              order_version=order['version']+1,reason=reason,created_at=now())
    await audit(s,user,'order.'+action,'order',id,{'status':status},{'status':target})
    await notify(s,order['customer_id'],'ORDER_STATUS',{'id':id,'status':target,'message':'Đơn hàng vừa được cập nhật.'})
    from .payments import request_refund,changed
    fresh=await one(s,'orders',T['orders'].c.id==id)
    if target in ('CANCELLED','REJECTED'):await request_refund(s,fresh)
    if target=='READY_FOR_PICKUP':await notify(s,order['customer_id'],'PICKUP_READY',{'id':id,'message':'Đơn đã sẵn sàng lấy. Xem điểm nhận và khung giờ trong đơn.','pickup':order['delivery_snapshot'].get('pickupSlot')})
    await changed(s,fresh)
    await catalog_event(s,list(offers))
    return await complete(s,user,scope,key,await get_order(s,user,id))

async def move_stock(s,user,offer,delta,kind,reference,order_id=None,reason=None):
    balance=offer['available_qty']+delta
    check(balance>=0,'INSUFFICIENT_STOCK','Tồn kho không đủ',409)
    await change(s,'offers',offer['id'],available_qty=balance,version=offer['version']+1,updated_at=now())
    await add(s,'inventory_movements',id=uid(),offer_id=offer['id'],actor_id=user['id'],kind=kind,
              reference_id=reference,order_id=order_id,quantity_delta=delta,balance_after=balance,reason=reason,created_at=now())
