from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select, func
from .db import T, now, uid, uuid, one, rows, add, change, check, text, number, public
from .commerce import version, audit, catalog_event, move_stock, idem, complete
from .events import emit

def date_time(value):
    try:
        result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return result.astimezone(timezone.utc).replace(tzinfo=None) if result.tzinfo else result
    except ValueError: check(False,'INVALID_DATE','Ngày giờ không hợp lệ')

FIELDS={
 'customer_groups':{'code':'code','name':'name','active':'active'},
 'categories':{'name':'name','active':'active'},
 'units':{'code':'code','label':'label'},
 'delivery_zones':{'code':'code','name':'name','description':'description','active':'active'},
 'delivery_policies':{'groupId':'group_id','zoneId':'zone_id','method':'method','minimumSubtotal':'minimum_subtotal','shippingFee':'shipping_fee','active':'active'},
 'pickup_slots':{'zoneId':'zone_id','name':'name','addressLine':'address_line','startsAt':'starts_at','endsAt':'ends_at','active':'active'},
 'moderation_rules':{'phrase':'phrase_normalized','matchMode':'match_mode','active':'active'},
}

async def configuration(s,user,table,id,body,method='POST'):
    old=await one(s,table,T[table].c.id==id,lock=True) if id else None
    if old and 'version' in old: version(old,body)
    if method=='DELETE':
        check('active' in T[table].c,'SOFT_DELETE_UNAVAILABLE','Dữ liệu đã tham chiếu không được xóa')
        values={'active':False}
    else:
        values={}
        for external,column in FIELDS[table].items():
            if external not in body: continue
            value=body[external]
            if column.endswith('_id'): value=uuid(value)
            elif column in ('minimum_subtotal','shipping_fee'): value=number(value,places=0)
            elif column.endswith('_at'): value=date_time(value)
            elif column=='active': check(isinstance(value,bool),'INVALID_BOOLEAN','Giá trị bật/tắt không hợp lệ')
            else: value=text(value,500 if column in ('description','address_line') else 150,1)
            values[column]=value
            length=getattr(T[table].c[column].type,'length',None)
            if length and isinstance(value,str):check(len(value)<=length,'INVALID_TEXT',f'{external}: tối đa {length} ký tự')
        merged={**(old or {}),**values}
        if table=='delivery_policies':
            check(merged.get('method') in ('INDIVIDUAL','COLLECTIVE'),'INVALID_DELIVERY','Cách giao không hợp lệ')
            group=await one(s,'customer_groups',T['customer_groups'].c.id==merged.get('group_id'))
            check(merged['method']!='COLLECTIVE' or (group['code']=='STUDENT' and Decimal(str(merged.get('shipping_fee',0)))==0),
                  'INVALID_DELIVERY','Giao tập trung chỉ cho sinh viên, không thu phí')
        if table=='pickup_slots': check(merged.get('ends_at',now())>merged.get('starts_at',now()),'INVALID_DATE','Giờ kết thúc phải sau giờ bắt đầu')
        if table=='moderation_rules':
            check(merged.get('match_mode') in ('TOKEN','PHRASE'),'INVALID_MODE','Cách lọc không hợp lệ')
            if 'phrase_normalized' in values:
                import unicodedata
                values['phrase_normalized']=unicodedata.normalize('NFC',values['phrase_normalized']).casefold()
    if old:
        if 'version' in old: values['version']=old['version']+1
        await change(s,table,id,**values)
    else:
        for column in T[table].c:
            if column.name=='id' or column.nullable or column.server_default is not None: continue
            check(column.name in values,'MISSING_FIELD','Thiếu trường '+column.name)
        id=uid(); await add(s,table,id=id,**values)
    await audit(s,user,table+'.update',table,id,old,values)
    emit(s,'admin:ops','CONFIG_CHANGED',{'table':table,'id':id})
    if table in ('customer_groups','delivery_policies','pickup_slots','delivery_zones'): await catalog_event(s,[])
    return await one(s,table,T[table].c.id==id)

async def product(s,user,id,body,method='POST'):
    old=await one(s,'products',T['products'].c.id==id,lock=True) if id else None
    if old: version(old,body)
    if method=='DELETE': values={'active':False,'deleted_at':now()}
    else:
        values={}
        for k,col in {'name':'name','sku':'sku','description':'description','categoryId':'category_id','unitId':'unit_id',
                      'quantityStep':'quantity_step','active':'active'}.items():
            if k not in body: continue
            v=body[k]
            if col.endswith('_id'): v=uuid(v)
            elif col=='quantity_step': v=number(v,minimum=Decimal('.001'))
            elif col=='active': check(isinstance(v,bool),'INVALID_BOOLEAN','Giá trị bật/tắt không hợp lệ')
            else: v=text(v,getattr(T['products'].c[col].type,'length',None) or 150,1 if col!='description' else 0)
            values[col]=v
        if old and any(k in values and values[k]!=old[k] for k in ('unit_id','quantity_step')):
            used=await one(s,'offers',T['offers'].c.product_id==id,required=False)
            check(not used,'UNIT_IN_USE','Không đổi đơn vị/bước khi sản phẩm đã mở bán',409)
    values['updated_at']=now()
    if old: await change(s,'products',id,version=old['version']+1,**values)
    else:
        check(all(k in values for k in ('name','sku','category_id','unit_id','quantity_step')),'MISSING_FIELD','Thiếu thông tin sản phẩm')
        id=uid(); await add(s,'products',id=id,version=1,created_at=now(),**values)
    if 'assetIds' in body:
        assets=body['assetIds']; check(isinstance(assets,list) and len(assets)<=5,'INVALID_IMAGES','Tối đa 5 ảnh')
        assets=[uuid(asset) for asset in assets]
        check(len(set(assets))==len(assets),'INVALID_IMAGES','Mỗi ảnh chỉ được chọn một lần')
        for asset in assets: await one(s,'media_assets',T['media_assets'].c.id==uuid(asset),T['media_assets'].c.owner_id==user['id'],
                                      T['media_assets'].c.purpose=='PRODUCT',T['media_assets'].c.state=='READY')
        await s.execute(T['product_images'].delete().where(T['product_images'].c.product_id==id))
        for position,asset in enumerate(assets): await add(s,'product_images',product_id=id,asset_id=asset,position=position)
    await audit(s,user,'product.update','product',id,old,values)
    await catalog_event(s,[])
    return await one(s,'products',T['products'].c.id==id)

async def offer(s,user,id,body):
    old=await one(s,'offers',T['offers'].c.id==id,lock=True) if id else None
    if old: version(old,body)
    prices=body.get('prices',[])
    check(isinstance(prices,list) and all(isinstance(price,dict) for price in prices),
          'INVALID_PRICES','Giá nhóm phải là danh sách các mức giá hợp lệ')
    if 'processingLocked' in body:
        check(isinstance(body['processingLocked'],bool),'INVALID_BOOLEAN','Khóa xử lý phải là giá trị đúng/sai')
    values={'updated_at':now()}
    if not old:
        for external,column in {'productId':'product_id','batchCode':'batch_code','opensAt':'opens_at','closesAt':'closes_at'}.items():
            v=body.get(external)
            values[column]=uuid(v) if column.endswith('_id') else date_time(v) if column.endswith('_at') else text(v,64,1)
        check(values['closes_at']>values['opens_at'],'INVALID_DATE','Giờ đóng phải sau giờ mở')
        values.update(sale_date=values['opens_at'].date(),available_qty=number(body.get('availableQty',0)),created_at=now(),version=1)
        product=await one(s,'products',T['products'].c.id==values['product_id'])
        check(values['available_qty']%product['quantity_step']==0,'INVALID_STEP','Tồn kho phải đúng bước đơn vị sản phẩm')
    status=body.get('status',old['status'] if old else 'DRAFT')
    check(status in ('DRAFT','OPEN','CLOSED'),'INVALID_STATUS','Trạng thái đợt không hợp lệ')
    values['status']=status
    if 'processingLocked' in body: values['processing_locked_at']=now() if body['processingLocked'] else None
    if old: await change(s,'offers',id,version=old['version']+1,**values)
    else:
        id=uid(); await add(s,'offers',id=id,**values)
        if values['available_qty']:
            await add(s,'inventory_movements',id=uid(),offer_id=id,actor_id=user['id'],kind='OPENING',reference_id=id,
                      quantity_delta=values['available_qty'],balance_after=values['available_qty'],created_at=now())
    for p in prices:
        groupid=uuid(p.get('groupId')); amount=number(p.get('unitPrice'),places=0)
        previous=await one(s,'offer_prices',T['offer_prices'].c.offer_id==id,T['offer_prices'].c.group_id==groupid,required=False)
        if previous:
            check(str(previous['version'])==str(p.get('expectedVersion')),'VERSION_CONFLICT','Giá đã đổi',409)
            await s.execute(T['offer_prices'].update().where(T['offer_prices'].c.offer_id==id,T['offer_prices'].c.group_id==groupid)
                            .values(unit_price=amount,version=previous['version']+1))
        else: await add(s,'offer_prices',offer_id=id,group_id=groupid,unit_price=amount,version=1)
    if status=='OPEN':
        prices=await rows(s,'offer_prices',T['offer_prices'].c.offer_id==id)
        check(bool(prices),'NO_PRICES','Cần ít nhất một giá nhóm trước khi mở bán')
    result=await one(s,'offers',T['offers'].c.id==id)
    if status=='OPEN' and (not old or old['status']!='OPEN'):
        fact=uid()
        await add(s,'notification_jobs',id=uid(),source_fact_id=fact,kind='PRODUCT_OPENED',product_id=result['product_id'],
                  payload={'offerId':id,'message':'Sản phẩm bạn quan tâm vừa mở bán.'},state='PENDING',attempts=0,created_at=now())
    await catalog_event(s,[id]); await audit(s,user,'offer.update','offer',id,old,values)
    return result

async def adjustment(s,user,body,key):
    prior=await idem(s,user,'inventory-adjust',key,body)
    if prior: return prior
    o=await one(s,'offers',T['offers'].c.id==uuid(body.get('offerId')),lock=True); version(o,body)
    delta=number(body.get('delta'),minimum=Decimal('-999999999'))
    check(delta!=0,'INVALID_NUMBER','Lượng điều chỉnh phải khác 0')
    product=await one(s,'products',T['products'].c.id==o['product_id'])
    check(delta%product['quantity_step']==0,'INVALID_STEP','Lượng điều chỉnh phải đúng bước đơn vị')
    reason=text(body.get('reason'),1000,3)
    await move_stock(s,user,o,delta,'MANUAL_ADJUST',uuid(key),reason=reason)
    await audit(s,user,'inventory.adjust','offer',o['id'],{'quantity':o['available_qty']},{'delta':delta,'reason':reason})
    await catalog_event(s,[o['id']])
    return await complete(s,user,'inventory-adjust',key,await one(s,'offers',T['offers'].c.id==o['id']))

async def reports(s,start,end):
    check(end>start and (end-start).days<=366,'INVALID_DATE','Khoảng báo cáo tối đa 366 ngày')
    o,i=T['orders'],T['order_items']
    states=(await s.execute(select(o.c.status,func.count().label('count')).where(o.c.created_at>=start,o.c.created_at<end).group_by(o.c.status))).mappings().all()
    revenue=(await s.execute(select(func.date(o.c.delivered_at).label('day'),func.count().label('orders'),
        func.sum(o.c.merchandise_total).label('merchandise'),func.sum(o.c.shipping_fee).label('shipping'))
        .where(o.c.status=='DELIVERED',o.c.delivered_at>=start,o.c.delivered_at<end).group_by(func.date(o.c.delivered_at)))).mappings().all()
    sold=(await s.execute(select(i.c.product_name_snapshot.label('name'),i.c.unit_snapshot.label('unit'),func.sum(i.c.quantity).label('quantity'),
        func.sum(i.c.line_total).label('revenue')).join(o,i.c.order_id==o.c.id).where(o.c.status=='DELIVERED',o.c.delivered_at>=start,o.c.delivered_at<end)
        .group_by(i.c.product_name_snapshot,i.c.unit_snapshot))).mappings().all()
    return public({'states':[dict(r) for r in states],'daily':[dict(r) for r in revenue],'sold':[dict(r) for r in sold]})
