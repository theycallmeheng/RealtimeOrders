from datetime import datetime, timezone
from decimal import Decimal
from ipaddress import ip_address
from urllib.parse import urlsplit
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
 'delivery_policies':{'groupId':'group_id','zoneId':'zone_id','method':'method','minimumSubtotal':'minimum_subtotal','shippingFee':'shipping_fee','active':'active','distanceEnabled':'distance_enabled','includedKm':'included_km','extraKmFee':'extra_km_fee','maxDistanceKm':'max_distance_km'},
 'pickup_slots':{'zoneId':'zone_id','name':'name','addressLine':'address_line','startsAt':'starts_at','endsAt':'ends_at','active':'active'},
 'moderation_rules':{'phrase':'phrase_normalized','matchMode':'match_mode','active':'active'},
}

def product_image_url(value):
    value=text(value,2048,1)
    check(not any(ch.isspace() or ord(ch)<32 for ch in value),
          'INVALID_IMAGE_URL','URL ảnh không được chứa khoảng trắng')
    try:
        parsed=urlsplit(value)
        hostname=parsed.hostname
        port=parsed.port
    except ValueError:
        check(False,'INVALID_IMAGE_URL','URL ảnh không hợp lệ')
    check(parsed.scheme.lower()=='https' and parsed.netloc and hostname,
          'INVALID_IMAGE_URL','URL ảnh phải bắt đầu bằng https://')
    check(parsed.username is None and parsed.password is None and port in (None,443),
          'INVALID_IMAGE_URL','URL ảnh không được chứa thông tin đăng nhập hoặc cổng lạ')
    hostname=hostname.rstrip('.').lower()
    check(hostname!='localhost' and not hostname.endswith(('.localhost','.local','.internal')),
          'INVALID_IMAGE_URL','URL ảnh phải trỏ tới máy chủ ảnh công khai')
    try:
        address=ip_address(hostname)
    except ValueError:
        address=None
    if address is not None:
        check(address.is_global,'INVALID_IMAGE_URL','URL ảnh phải trỏ tới máy chủ ảnh công khai')
    return value

async def configuration(s,user,table,id,body,method='POST'):
    old=await one(s,table,T[table].c.id==id,lock=True) if id else None
    if old and 'version' in old: version(old,body)
    if method=='DELETE':
        check('active' in T[table].c,'SOFT_DELETE_UNAVAILABLE','Dữ liệu đã tham chiếu không được xóa')
        if table=='customer_groups':
            check(old is not None,'NOT_FOUND','Không tìm thấy nhóm khách hàng',404)
            check(old['code']!='WORKER','GROUP_REQUIRED','Không thể xóa nhóm mặc định của tài khoản mới',409)
            if old['code']=='STUDENT':
                collective=await one(s,'delivery_policies',T['delivery_policies'].c.group_id==old['id'],
                    T['delivery_policies'].c.method=='COLLECTIVE',T['delivery_policies'].c.active==True,required=False)
                check(not collective,'GROUP_IN_USE','Hãy tắt chính sách giao tập trung trước khi xóa nhóm sinh viên',409)
        values={'active':False}
    else:
        values={}
        for external,column in FIELDS[table].items():
            if external not in body: continue
            value=body[external]
            if column.endswith('_id'): value=uuid(value)
            elif column in ('minimum_subtotal','shipping_fee','extra_km_fee'): value=number(value,places=0)
            elif column in ('included_km','max_distance_km'): value=number(value)
            elif column.endswith('_at'): value=date_time(value)
            elif column in ('active','distance_enabled'): check(isinstance(value,bool),'INVALID_BOOLEAN','Giá trị bật/tắt không hợp lệ')
            else: value=text(value,500 if column in ('description','address_line') else 150,1)
            values[column]=value
            length=getattr(T[table].c[column].type,'length',None)
            if length and isinstance(value,str):check(len(value)<=length,'INVALID_TEXT',f'{external}: tối đa {length} ký tự')
        merged={**(old or {}),**values}
        if table=='customer_groups' and old:
            if old['code'] in ('STUDENT','WORKER') and 'code' in values:
                check(values['code']==old['code'],'GROUP_CODE_LOCKED','Mã nhóm hệ thống không thể đổi',409)
            if old['active'] and values.get('active',old['active']) is False:
                check(old['code']!='WORKER','GROUP_REQUIRED','Không thể tắt nhóm mặc định của tài khoản mới',409)
                if old['code']=='STUDENT':
                    collective=await one(s,'delivery_policies',T['delivery_policies'].c.group_id==old['id'],
                        T['delivery_policies'].c.method=='COLLECTIVE',T['delivery_policies'].c.active==True,required=False)
                    check(not collective,'GROUP_IN_USE','Hãy tắt chính sách giao tập trung trước khi xóa nhóm sinh viên',409)
        if table=='delivery_policies':
            if merged.get('distance_enabled'):
                check(all(merged.get(k) is not None for k in ('included_km','max_distance_km','extra_km_fee')) and
                      Decimal(str(merged['max_distance_km']))>0 and Decimal(str(merged['included_km']))<=Decimal(str(merged['max_distance_km'])),
                      'INVALID_DISTANCE_POLICY','Nhập km bao gồm, km tối đa và phí km vượt hợp lệ')
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
    if table in ('customer_groups','delivery_policies','pickup_slots','delivery_zones'):
        if table=='customer_groups' and old and old['active'] and values.get('active',old['active']) is False:
            from .menus import invalidate
            await invalidate(s,user)
            emit(s,'catalog:'+old['id'],'CATALOG_CHANGED',{'refresh':True})
        await catalog_event(s,[])
    return await one(s,table,T[table].c.id==id)

async def product(s,user,id,body,method='POST'):
    from .menus import group_ids,invalidate
    old=await one(s,'products',T['products'].c.id==id,lock=True) if id else None
    if old: version(old,body)
    if method=='DELETE': values={'active':False,'deleted_at':now()}
    else:
        values={}
        for k,col in {'name':'name','description':'description','categoryId':'category_id','unitId':'unit_id',
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
    if method!='DELETE':
        for field,col in (('defaultCostPrice','default_cost_price'),('defaultSalePrice','default_sale_price')):
            if field in body: values[col]=None if body[field] in ('',None) else number(body[field],places=0)
        if 'allowedGroupIds' in body: values['allowed_group_ids']=await group_ids(s,body['allowedGroupIds'])
    values['updated_at']=now()
    if old: await change(s,'products',id,version=old['version']+1,**values)
    else:
        check(all(k in values for k in ('name','category_id','unit_id','quantity_step')),'MISSING_FIELD','Thiếu thông tin sản phẩm')
        sequence=await one(s,'sku_sequences',T['sku_sequences'].c.sequence_key=='product',lock=True)
        sku_number=int(sequence['next_value'])
        values['sku']=f'SKU-{sku_number:06d}'
        await s.execute(T['sku_sequences'].update().where(
            T['sku_sequences'].c.sequence_key=='product').values(next_value=sku_number+1))
        id=uid(); await add(s,'products',id=id,version=1,created_at=now(),**values)
    image_entries=None
    if 'images' in body:
        image_entries=body['images']
    elif 'assetIds' in body:
        assets=body['assetIds']
        check(isinstance(assets,list) and len(assets)<=5,'INVALID_IMAGES','Tối đa 5 ảnh')
        image_entries=[{'assetId':asset} for asset in assets]
    if image_entries is not None:
        check(isinstance(image_entries,list) and len(image_entries)<=5,
              'INVALID_IMAGES','Tối đa 5 ảnh')
        normalized=[]; seen=set()
        for entry in image_entries:
            check(isinstance(entry,dict) and set(entry).issubset({'assetId','url'}),
                  'INVALID_IMAGES','Thông tin ảnh không hợp lệ')
            has_asset='assetId' in entry and entry['assetId'] is not None
            has_url='url' in entry and entry['url'] is not None
            check(has_asset != has_url,'INVALID_IMAGES','Mỗi ảnh cần đúng một assetId hoặc URL')
            if has_asset:
                asset=uuid(entry['assetId'])
                check(('asset',asset) not in seen,'INVALID_IMAGES','Mỗi ảnh chỉ được chọn một lần')
                seen.add(('asset',asset))
                await one(s,'media_assets',T['media_assets'].c.id==asset,T['media_assets'].c.owner_id==user['id'],
                          T['media_assets'].c.purpose=='PRODUCT',T['media_assets'].c.state=='READY')
                normalized.append((asset,None))
            else:
                source_url=product_image_url(entry['url'])
                check(('url',source_url) not in seen,'INVALID_IMAGES','URL ảnh bị lặp')
                seen.add(('url',source_url))
                normalized.append((None,source_url))
        await s.execute(T['product_images'].delete().where(T['product_images'].c.product_id==id))
        for position,(asset,source_url) in enumerate(normalized):
            await add(s,'product_images',product_id=id,asset_id=asset,source_url=source_url,position=position)
    await audit(s,user,'product.update','product',id,old,values)
    if 'allowed_group_ids' in values or method=='DELETE': await invalidate(s,user)
    await catalog_event(s,[])
    return await one(s,'products',T['products'].c.id==id)

async def offer(s,user,id,body):
    """Compatibility adapter: all offer writes obey the daily menu rules."""
    from . import menus
    if 'prices' in body:
        check(isinstance(body['prices'],list) and all(isinstance(p,dict) for p in body['prices']),'INVALID_PRICES','Giá nhóm không hợp lệ')
    if 'processingLocked' in body:
        check(isinstance(body['processingLocked'],bool),'INVALID_BOOLEAN','Khóa xử lý không hợp lệ')
    from datetime import datetime
    old=await one(s,'offers',T['offers'].c.id==id) if id else None
    if old:
        version(old,body)
        check(old['menu_id'] and not old['archived_at'],'OFFER_ARCHIVED','Đợt cũ chỉ được xem trong lịch sử',409)
        menu=await menus.detail(s,old['menu_id'])
    else:
        check(body.get('productId'),'MISSING_FIELD','Thiếu sản phẩm')
        day=(date_time(body.get('opensAt'))+menus.VN).date()
        if body.get('menuId'):
            menu=await menus.detail(s,uuid(body['menuId']))
            check(str(menu['sale_date'])==day.isoformat(),'MENU_DATE_MISMATCH','Menu được chọn không thuộc ngày mở bán này',409)
        else:
            same_day=await rows(s,'daily_menus',T['daily_menus'].c.sale_date==day,limit=2,
                                order=T['daily_menus'].c.opens_at.desc())
            check(len(same_day)<=1,'MENU_ID_REQUIRED',
                  'Ngày này có nhiều đợt; cần chọn menuId để thêm sản phẩm đúng đợt',409)
            menu=await menus.detail(s,same_day[0]['id']) if same_day else None
        check(not menu or not any(i['product_id']==body['productId'] for i in menu['items']),
              'DUPLICATE_ITEM','Sản phẩm đã có trong menu ngày; hãy sửa dòng hiện có',409)
    entries=[]
    for entry in menu['items'] if menu else []:
        entries.append({'productId':entry['product_id'],'availableQty':entry['available_qty'],'costPrice':entry['cost_price'],
            'enabled':entry['status']=='OPEN','expectedVersion':entry['version'],
            'prices':[{'groupId':v['group_id'],'unitPrice':v['unit_price']} for v in entry['prices']]})
    item=next((i for i in entries if old and i['productId']==old['product_id']),None)
    if item is None:
        item={'productId':body['productId'],'availableQty':body.get('availableQty','0'),'prices':[]}
        entries.append(item)
    if 'costPrice' in body:item['costPrice']=body['costPrice']
    if 'prices' in body:
        known={p['groupId']:p for p in item['prices']}
        for price in body['prices']:
            if old:
                previous=next((v for v in menu['items'] if v['id']==id),{}).get('prices',[])
                prev=next((v for v in previous if v['group_id']==price['groupId']),None)
                if prev: check(str(prev['version'])==str(price.get('expectedVersion')),'VERSION_CONFLICT','Giá đã đổi',409)
            known[price['groupId']]=price
        item['prices']=list(known.values())
    item['enabled']=body.get('status',old['status'] if old else 'OPEN')=='OPEN'
    status='OPEN' if any(i.get('enabled',True) for i in entries) else 'DRAFT'
    result=await menus.save(s,user,menu['id'] if menu else None,{'saleDate':str(menu['sale_date'] if menu else day),
        'expectedVersion':menu['version'] if menu else None,'status':status,'items':entries})
    offer=next(i for i in result['items'] if i['product_id']==item['productId'])
    if old and old['status']!='OPEN' and item['enabled'] and menu['status']=='OPEN':
        await add(s,'notification_jobs',id=uid(),source_fact_id=uid(),kind='PRODUCT_OPENED',product_id=offer['product_id'],
            payload={'offerId':offer['id'],'message':'Sản phẩm bạn quan tâm vừa mở bán.'},state='PENDING',attempts=0,created_at=now())
    if 'processingLocked' in body:
        check(isinstance(body['processingLocked'],bool),'INVALID_BOOLEAN','Khóa xử lý không hợp lệ')
        await change(s,'offers',offer['id'],processing_locked_at=now() if body['processingLocked'] else None)
    return await one(s,'offers',T['offers'].c.id==offer['id'])

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
