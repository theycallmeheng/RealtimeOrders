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
    m['items']=[o for o in await catalog(s,{'id':'00000000-0000-0000-0000-000000000000','group_id':None},admin=True,menu_id=id)
                if o['menu_id']==id]
    return public(m)


async def current(s,user):
    from .commerce import catalog
    current_menu=(await s.execute(select(T['daily_menus']).where(
        T['daily_menus'].c.status=='OPEN',T['daily_menus'].c.opens_at<=now(),
        T['daily_menus'].c.closes_at>now()).order_by(T['daily_menus'].c.opens_at.desc()).limit(1))).mappings().first()
    menu=dict(current_menu) if current_menu else None
    group=await one(s,'customer_groups',T['customer_groups'].c.id==user['group_id'],required=False)
    allowed=menu and group and group['active'] and (menu['allowed_group_ids'] is None or user['group_id'] in menu['allowed_group_ids'])
    return public({'saleDate':today(),'menu':{k:v for k,v in menu.items() if k!='allowed_group_ids'} if allowed else None,
                   'offers':await catalog(s,user),'serverTime':now()})


async def notification_feed(s,user,offset=0):
    from .commerce import catalog
    n=T['notifications']
    notifications=[dict(r) for r in (await s.execute(select(n).where(n.c.user_id==user['id'])
        .order_by(n.c.created_at.desc(),n.c.id.desc()).limit(50).offset(offset))).mappings()]
    allowed={o['id'] for o in await catalog(s,user)} if any(n['kind']=='PRODUCT_OPENED' for n in notifications) else set()
    return [n for n in notifications if not n['kind'].startswith('REQUEST_') and
            (n['kind']!='PRODUCT_OPENED' or n['payload'].get('offerId') in allowed)]


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
        overlap_conditions=[T['daily_menus'].c.status=='OPEN',
                           T['daily_menus'].c.opens_at<closes,
                           T['daily_menus'].c.closes_at>opens]
        if old: overlap_conditions.append(T['daily_menus'].c.id!=old['id'])
        overlap=await one(s,'daily_menus',*overlap_conditions,lock=True,required=False)
        check(not overlap,'MENU_WINDOW_CONFLICT',
              'Thời gian này đang chồng với một đợt mở bán khác',409)
    if old and entries is not None:
        check({o['product_id'] for o in existing}<={i.get('productId') for i in entries},
              'KEEP_MENU_ITEMS','Giữ món đã tạo; dùng nút Ngừng bán để tắt món')
    id=id or uid()
    data=dict(sale_date=day,status=status,opens_at=opens,closes_at=closes,allowed_group_ids=groups,updated_at=now())
    if old: await change(s,'daily_menus',id,version=old['version']+1,**data)
    else: await add(s,'daily_menus',id=id,version=1,created_at=now(),**data)
    product_ids=[uuid(i.get('productId')) for i in entries or []]
    check(len(product_ids)==len(set(product_ids)),'DUPLICATE_ITEM','Mỗi sản phẩm chỉ xuất hiện một lần')
    for item in sorted(entries or [],key=lambda i:i['productId']):
        p=await one(s,'products',T['products'].c.id==item['productId'],lock=True)
        check(p['active'] and not p['deleted_at'],'PRODUCT_UNAVAILABLE','Sản phẩm đã ngừng dùng')
        prev=next((o for o in existing if o['product_id']==p['id']),None)
        if prev: prev=await one(s,'offers',T['offers'].c.id==prev['id'],lock=True)
        if p['allowed_group_ids'] is None:
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
        prices=item.get('prices',[])
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
            'allowedGroupIds':i['allowed_group_ids'] if i['product_allowed_group_ids'] is None else None,
            'prices':[{'groupId':p['group_id'],'unitPrice':p['unit_price']} for p in i['prices']]} for i in source['items']]
    return await save(s,user,None,{'saleDate':body.get('saleDate'),'status':'DRAFT','items':items,'allowedGroupIds':source['allowed_group_ids']})


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
