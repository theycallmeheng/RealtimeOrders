"""Daily sales and public audience rules; money remains server authoritative."""
import asyncio
import json
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy import select, and_, or_, update, func
from .db import T, Session, now, uid, uuid, one, rows, add, change, check, number, public
from .events import emit, flush_events

VN = timedelta(hours=7)


def today():
    return (now()+VN).date()


def bounds(day):
    if isinstance(day, str):
        try: day=date.fromisoformat(day)
        except ValueError: check(False,'INVALID_DATE','Ngày không hợp lệ')
    start=datetime.combine(day,datetime.min.time())-VN
    return start,start+timedelta(days=1)


def effective_status(menu, at=None):
    """Stored OPEN enables a schedule; availability also depends on its bounds."""
    if menu['status'] != 'OPEN':
        return menu['status']
    at = now() if at is None else at
    if at >= menu['closes_at']:
        return 'EXPIRED'
    if at < menu['opens_at']:
        return 'SCHEDULED'
    return 'SOLD_OUT' if menu.get('sold_out', False) else 'OPEN'


async def stock_status(s, menus, at=None):
    """Derive availability; never persist CLOSED when stock temporarily reaches zero."""
    if not menus: return []
    o,p=T['offers'],T['products']
    maxima=dict((await s.execute(select(o.c.menu_id,func.max(o.c.available_qty)).join(p,o.c.product_id==p.c.id)
        .where(o.c.menu_id.in_([m['id'] for m in menus]),o.c.archived_at==None,o.c.status=='OPEN',
               p.c.active==True,p.c.deleted_at==None).group_by(o.c.menu_id))).all())
    return [{**m,'sold_out':m['id'] in maxima and maxima[m['id']]<=0,
             'effective_status':effective_status({**m,'sold_out':m['id'] in maxima and maxima[m['id']]<=0},at)} for m in menus]


def audience(column, group_id):
    return or_(column.is_(None),func.json_type(column)=='NULL', func.json_contains(column,json.dumps(group_id))==1)


async def group_ids(s, value):
    if value is None: return None
    check(isinstance(value,list) and 0<len(value)<=100,'INVALID_GROUPS','Chọn ít nhất một nhóm hoặc Tất cả nhóm')
    result=sorted({uuid(id) for id in value})
    active=await rows(s,'customer_groups',T['customer_groups'].c.active==True,limit=100)
    check(set(result)<={g['id'] for g in active},'INVALID_GROUPS','Nhóm không tồn tại hoặc đã ngừng dùng')
    return result


async def visible(s,user,offer,product=None):
    if not offer.get('menu_id') or offer.get('archived_at'): return False
    product=product or await one(s,'products',T['products'].c.id==offer['product_id'])
    if 'allowed_group_ids' not in offer:
        offer=await one(s,'offers',T['offers'].c.id==offer['id'])
    group=await one(s,'customer_groups',T['customer_groups'].c.id==user['group_id'],required=False)
    menu=await one(s,'daily_menus',T['daily_menus'].c.id==offer['menu_id'])
    return (menu['status']=='OPEN' and menu['opens_at']<=now()<menu['closes_at']
            and group and group['active'] and offer['status']=='OPEN' and product['active'] and not product['deleted_at']
            and all(a is None or user['group_id'] in a for a in
                    (menu['allowed_group_ids'],product['allowed_group_ids'],offer.get('allowed_group_ids'))))


async def epoch(s):
    row=await one(s,'system_settings',T['system_settings'].c.setting_key=='dataset_epoch',required=False)
    return row['value_json']['value'] if row else 'daily-v1'


async def invalidate(s, user):
    row=await one(s,'system_settings',T['system_settings'].c.setting_key=='dataset_epoch',lock=True,required=False)
    values=dict(value_json={'value':uid()},updated_by=user['id'],updated_at=now())
    if row:
        await s.execute(update(T['system_settings']).where(T['system_settings'].c.setting_key=='dataset_epoch')
                        .values(**values,version=row['version']+1))
    else: await add(s,'system_settings',setting_key='dataset_epoch',version=1,**values)
    # Old catalog payloads must not reveal revoked products through a later replay.
    e=T['stream_events']
    await s.execute(update(e).where(e.c.topic.like('catalog:%')).values(payload={'refresh':True}))


async def detail(s,id):
    from .commerce import catalog
    m=await one(s,'daily_menus',T['daily_menus'].c.id==id)
    m=(await stock_status(s,[m]))[0]
    m['items']=[o for o in await catalog(s,{'id':'00000000-0000-0000-0000-000000000000','group_id':None},admin=True,menu_id=id)
                if o['menu_id']==id]
    return public(m)


async def current(s,user):
    from .commerce import catalog
    active=(await s.execute(select(T['daily_menus']).where(
        T['daily_menus'].c.status=='OPEN',T['daily_menus'].c.opens_at<=now(),
        T['daily_menus'].c.closes_at>now()).order_by(T['daily_menus'].c.opens_at.desc(),T['daily_menus'].c.id).limit(100))).mappings().all()
    group=await one(s,'customer_groups',T['customer_groups'].c.id==user['group_id'],required=False)
    allowed=[dict(m) for m in active if group and group['active'] and
             (m['allowed_group_ids'] is None or user['group_id'] in m['allowed_group_ids'])]
    active_menus=await stock_status(s,allowed)
    safe=[{k:v for k,v in m.items() if k!='allowed_group_ids'} for m in active_menus]
    return public({'saleDate':today(),'menu':safe[0] if safe else None,'menus':safe,
                   'offers':await catalog(s,user),'serverTime':now()})



async def upcoming(s, user):
    """Products not assigned to a sales round; expose only customer-safe fields."""
    group=await one(s,'customer_groups',T['customer_groups'].c.id==user['group_id'],required=False)
    if not group or not group['active']: return []
    p,o,u=T['products'],T['offers'],T['units']
    assigned=select(o.c.product_id).where(o.c.menu_id!=None,o.c.archived_at==None)
    query=select(p.c.id.label('product_id'),p.c.name,p.c.description,p.c.category_id,u.c.label.label('unit')).join(u,p.c.unit_id==u.c.id).where(
        p.c.active==True,p.c.deleted_at==None,p.c.id.not_in(assigned),audience(p.c.allowed_group_ids,user['group_id'])).order_by(p.c.name).limit(500)
    products=[dict(r) for r in (await s.execute(query)).mappings()]
    if not products: return []
    images=await rows(s,'product_images',T['product_images'].c.product_id.in_([p['product_id'] for p in products]),limit=2500,order=T['product_images'].c.position)
    followed={r['product_id'] for r in await rows(s,'product_subscriptions',T['product_subscriptions'].c.user_id==user['id'],limit=500)}
    for product in products:
        product['images']=[i['asset_id'] or i['source_url'] for i in images if i['product_id']==product['product_id'] and (i['asset_id'] or i['source_url'])]
        product['subscribed']=product['product_id'] in followed
    return public(products)


async def notification_feed(s,user,offset=0):
    from .commerce import catalog
    n=T['notifications']
    notifications=[dict(r) for r in (await s.execute(select(n).where(n.c.user_id==user['id'])
        .order_by(n.c.created_at.desc(),n.c.id.desc()).limit(50).offset(offset))).mappings()]
    allowed={o['id'] for o in await catalog(s,user)} if any(n['kind']=='PRODUCT_OPENED' for n in notifications) else set()
    return [n for n in notifications if not n['kind'].startswith('REQUEST_') and
            (n['kind']!='PRODUCT_OPENED' or n['payload'].get('offerId') in allowed)]


async def ensure_distinct_products(s, menu_id, product_ids, opens, closes):
    """Product row locks serialize overlapping opens, including different rooms/groups."""
    o,m=T['offers'],T['daily_menus']
    for product_id in sorted(set(product_ids)):
        product=await one(s,'products',T['products'].c.id==product_id,lock=True)
        conflict=(await s.execute(select(m.c.id).join(o,o.c.menu_id==m.c.id).where(
            o.c.product_id==product_id,o.c.status=='OPEN',o.c.archived_at==None,
            m.c.status=='OPEN',m.c.id!=(menu_id or ''),m.c.opens_at<closes,m.c.closes_at>opens).limit(1))).scalar_one_or_none()
        check(conflict is None,'PRODUCT_ALREADY_OPEN',
              'Sản phẩm '+product['name']+' đã nằm trong đợt mở bán trùng thời gian. Hãy bỏ chọn sản phẩm hoặc đổi lịch bán.',409)


async def save(s,user,id,body):
    from .commerce import version,audit,catalog_event,move_stock
    old=await one(s,'daily_menus',T['daily_menus'].c.id==id,lock=True) if id else None
    if old: version(old,body)
    try: day=date.fromisoformat(body.get('saleDate',str(old['sale_date']) if old else ''))
    except (ValueError,TypeError): check(False,'INVALID_DATE','Chọn ngày bán hợp lệ')
    check(not old or day==old['sale_date'],'IMMUTABLE_DATE','Sao chép menu để đổi sang ngày khác')
    start,end=bounds(day)
    from .admin import date_time
    opens=date_time(body['opensAt']) if body.get('opensAt') else old['opens_at'] if old else start
    closes=date_time(body['closesAt']) if body.get('closesAt') else old['closes_at'] if old else end
    check(start<=opens<end and opens<closes,'INVALID_DATE',
          'Giờ mở phải nằm trong ngày bắt đầu và giờ đóng phải sau giờ mở')
    groups=await group_ids(s,body.get('allowedGroupIds',old['allowed_group_ids'] if old else None))
    mode=body.get('audienceMode',old.get('audience_mode','MENU') if old else 'MENU')
    check(mode in ('MENU','PRODUCT'),'INVALID_AUDIENCE_MODE','Chọn cách phân nhóm hợp lệ')
    check(mode!='PRODUCT' or groups is None,'INVALID_GROUPS',
          'Tùy chỉnh theo sản phẩm không dùng cùng nhóm chung của menu')
    status=body.get('status',old['status'] if old else 'DRAFT')
    check(status in ('OPEN','CLOSED','DRAFT'),'INVALID_STATUS','Trạng thái menu không hợp lệ')
    check(status!='OPEN' or closes>now(),'MENU_EXPIRED','Thời điểm đóng đợt phải ở tương lai',409)
    check(status!='OPEN' or day>=today() or
          (old and old['status']=='OPEN' and old['opens_at']<=now()<old['closes_at']),
          'MENU_EXPIRED','Không mở lại menu ngày đã qua',409)
    entries=body.get('items')
    check(entries is None or isinstance(entries,list) and len(entries)<=100,'INVALID_ITEMS','Menu tối đa 100 sản phẩm')
    existing=await rows(s,'offers',T['offers'].c.menu_id==id,limit=100) if old else []
    if status=='OPEN':
        selected_ids=([uuid(i.get('productId')) for i in entries if i.get('enabled',True) is not False]
                      if entries is not None else [o['product_id'] for o in existing if o['status']=='OPEN'])
        await ensure_distinct_products(s,id,selected_ids,opens,closes)

    if old and entries is not None:
        selected={i.get('productId') for i in entries}
        for removed in sorted((o for o in existing if o['product_id'] not in selected),key=lambda o:o['id']):
            current=await one(s,'offers',T['offers'].c.id==removed['id'],lock=True)
            if current['status']!='CLOSED':
                # Preserve IDs, stock, prices and order references; only stop selling.
                await change(s,'offers',current['id'],status='CLOSED',version=current['version']+1,updated_at=now())
                await audit(s,user,'menu.item.remove','offer',current['id'],
                            {'status':current['status']},{'status':'CLOSED'})
    id=id or uid()
    data=dict(sale_date=day,status=status,opens_at=opens,closes_at=closes,allowed_group_ids=groups,audience_mode=mode,updated_at=now())
    if old: await change(s,'daily_menus',id,version=old['version']+1,**data)
    else: await add(s,'daily_menus',id=id,version=1,created_at=now(),**data)
    product_ids=[uuid(i.get('productId')) for i in entries or []]
    check(len(product_ids)==len(set(product_ids)),'DUPLICATE_ITEM','Mỗi sản phẩm chỉ xuất hiện một lần')
    for item in sorted(entries or [],key=lambda i:i['productId']):
        p=await one(s,'products',T['products'].c.id==item['productId'],lock=True)
        check(p['active'] and not p['deleted_at'],'PRODUCT_UNAVAILABLE','Sản phẩm đã ngừng dùng')
        prev=next((o for o in existing if o['product_id']==p['id']),None)
        if prev: prev=await one(s,'offers',T['offers'].c.id==prev['id'],lock=True)
        if mode=='MENU':
            check(item.get('allowedGroupIds') is None,'MENU_AUDIENCE_LOCKED',
                  'Nhóm mua của món này kế thừa nhóm chung của menu',409)
            audience_ids=None
        elif p['allowed_group_ids'] is None:
            audience_ids=await group_ids(s,item.get('allowedGroupIds',prev['allowed_group_ids'] if prev else None))
        else:
            check(item.get('allowedGroupIds') is None,'PRODUCT_AUDIENCE_LOCKED',
                  'Nhóm của món này được khóa theo cấu hình sản phẩm',409)
            audience_ids=None
        cost=number(item['costPrice'],places=0) if item.get('costPrice') not in (None,'') else p['default_cost_price']
        quantity=number(item.get('availableQty',prev['available_qty'] if prev else 0))
        check(quantity%p['quantity_step']==0,'INVALID_STEP','Số lượng phải đúng bước đơn vị')
        enabled=item.get('enabled',True)
        check(isinstance(enabled,bool),'INVALID_BOOLEAN','Trạng thái món không hợp lệ')
        offer_id=prev['id'] if prev else uid()
        values=dict(allowed_group_ids=audience_ids,cost_price=cost,status='OPEN' if enabled else 'CLOSED',
                    opens_at=opens,closes_at=closes,updated_at=now())
        if prev:
            check(str(prev['version'])==str(item.get('expectedVersion')),'VERSION_CONFLICT','Tồn hoặc giá món đã đổi; tải lại menu',409)
            delta=quantity-prev['available_qty']
            if delta: await move_stock(s,user,prev,delta,'MANUAL_ADJUST',uid(),reason='Điều chỉnh trong menu ngày')
            if any(values[k]!=prev[k] for k in values if k!='updated_at'):
                await change(s,'offers',offer_id,version=prev['version']+(2 if delta else 1),**values)
        else:
            await add(s,'offers',id=offer_id,menu_id=id,product_id=p['id'],sale_date=day,batch_code=id,
                      available_qty=quantity,version=1,created_at=now(),**values)
            if quantity: await add(s,'inventory_movements',id=uid(),offer_id=offer_id,actor_id=user['id'],kind='OPENING',
                reference_id=offer_id,quantity_delta=quantity,balance_after=quantity,created_at=now())
        from .pricing import menu_prices, load_rules
        active_groups=await rows(s,'customer_groups',T['customer_groups'].c.active==True,limit=100)
        prices=menu_prices(cost,active_groups,await load_rules(s)) if cost is not None else []
        check(isinstance(prices,list) and len(prices)<=100,'INVALID_PRICES','Giá nhóm không hợp lệ')
        seen=set()
        for price in prices:
            gid=uuid(price.get('groupId')); check(gid not in seen,'INVALID_PRICES','Không lặp nhóm giá'); seen.add(gid)
            await one(s,'customer_groups',T['customer_groups'].c.id==gid,T['customer_groups'].c.active==True)
            amount=number(price.get('unitPrice'),places=0)
            t=T['offer_prices']
            previous=await one(s,'offer_prices',t.c.offer_id==offer_id,t.c.group_id==gid,required=False)
            if previous:
                if previous['unit_price']!=amount:
                    await s.execute(update(t).where(t.c.offer_id==offer_id,t.c.group_id==gid).values(unit_price=amount,version=previous['version']+1))
            else: await add(s,'offer_prices',offer_id=offer_id,group_id=gid,unit_price=amount,version=1)
        # Prices are the complete selected set, not an append-only list.
        await s.execute(T['offer_prices'].delete().where(T['offer_prices'].c.offer_id==offer_id,~T['offer_prices'].c.group_id.in_(seen)))
    if mode=='MENU' and entries is None:
        # A mode-only update must also remove stale per-item overrides.
        o=T['offers']
        await s.execute(update(o).where(o.c.menu_id==id,o.c.allowed_group_ids.is_not(None))
            .values(allowed_group_ids=None,version=o.c.version+1,updated_at=now()))
    if status=='OPEN':
        check(bool(entries or existing),'EMPTY_MENU','Chọn sản phẩm trước khi mở bán')
        all_items=await rows(s,'offers',T['offers'].c.menu_id==id,T['offers'].c.status=='OPEN',limit=100)
        check(bool(all_items),'EMPTY_MENU','Cần ít nhất một món đang bán')
        for item in all_items:
            check(item['cost_price'] is not None,'COST_REQUIRED','Nhập giá vốn cho từng món trước khi mở bán')
            check((old is not None and old['status']=='OPEN') or item['available_qty']>0,'STOCK_REQUIRED','Nhập lượng bán trước khi mở menu')
            pp=await one(s,'products',T['products'].c.id==item['product_id'])
            prices=await rows(s,'offer_prices',T['offer_prices'].c.offer_id==item['id'])
            check(any((groups is None or price['group_id'] in groups) and
                (pp['allowed_group_ids'] is None or price['group_id'] in pp['allowed_group_ids']) and
                (item['allowed_group_ids'] is None or price['group_id'] in item['allowed_group_ids']) for price in prices),
                'NO_PRICES','Mỗi món cần giá cho ít nhất một nhóm được phép mua')
    await invalidate(s,user)
    await catalog_event(s,[])
    await audit(s,user,'menu.save','menu',id,old,data)
    if status=='OPEN' and (not old or old['status']!='OPEN'):
        for item in await rows(s,'offers',T['offers'].c.menu_id==id,T['offers'].c.status=='OPEN',limit=100):
            await add(s,'notification_jobs',id=uid(),source_fact_id=uid(),kind='PRODUCT_OPENED',product_id=item['product_id'],
                payload={'offerId':item['id'],'message':'Sản phẩm bạn quan tâm vừa mở bán.'},state='PENDING',attempts=0,created_at=now())
    return await detail(s,id)


async def copy(s,user,id,body):
    source=await detail(s,id)
    items=[{'productId':i['product_id'],'availableQty':'0','costPrice':i['cost_price'],
            'allowedGroupIds':i['allowed_group_ids'] if source.get('audience_mode')=='PRODUCT' and i['product_allowed_group_ids'] is None else None,
            'prices':[{'groupId':p['group_id'],'unitPrice':p['unit_price']} for p in i['prices']]} for i in source['items'] if i['status']=='OPEN']
    return await save(s,user,None,{'saleDate':body.get('saleDate'),'status':'DRAFT','items':items,'allowedGroupIds':source['allowed_group_ids'],'audienceMode':source.get('audience_mode','MENU')})


async def boundary_monitor():
    """Publish when schedules cross a boundary, including the VN day boundary."""
    from .commerce import catalog_event
    previous=None
    while True:
        try:
            async with Session.begin() as s:
                menus=await rows(s,'daily_menus',T['daily_menus'].c.status=='OPEN',
                                 T['daily_menus'].c.closes_at>now(),limit=100,
                                 order=T['daily_menus'].c.opens_at)
                state=(str(today()),tuple((m['id'],m['status'],m['opens_at']<=now()<m['closes_at']) for m in menus))
                if previous is not None and state!=previous:
                    await catalog_event(s,[]); await flush_events(s)
                previous=state
        except asyncio.CancelledError: raise
        except Exception:
            import logging
            logging.getLogger(__name__).warning('menu_schedule_unavailable')
        await asyncio.sleep(1)
