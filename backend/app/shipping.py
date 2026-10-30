"""Goong adapter. Network requests never run under inventory locks."""
import base64
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
import httpx
from .config import settings
from .db import T, now, uid, uuid, one, add, check, number, digest, public, Fault


async def goong(path, params):
    check(bool(settings.goong_api_key),'MAP_NOT_CONFIGURED','Người bán chưa cấu hình API Goong',503)
    try:
        async with httpx.AsyncClient(timeout=8,trust_env=False) as client:
            response=await client.get('https://rsapi.goong.io/'+path,params={**params,'api_key':settings.goong_api_key})
        check(response.status_code==200,'MAP_UNAVAILABLE','Dịch vụ bản đồ đang bận hoặc hết hạn mức; hãy thử lại',503)
        data=response.json()
        check(data.get('status','OK') in ('OK','ZERO_RESULTS'),'MAP_UNAVAILABLE','Dịch vụ bản đồ chưa trả kết quả hợp lệ',503)
        return data
    except (httpx.HTTPError,ValueError,KeyError):
        raise Fault('MAP_UNAVAILABLE','Không kết nối được dịch vụ bản đồ; hãy thử lại',503)


def location_token(data):
    raw=base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).decode()
    signature=hmac.new(settings.app_secret.encode(),raw.encode(),hashlib.sha256).hexdigest()
    return raw+'.'+signature


def verify_location(token):
    try:
        raw,signature=token.split('.')
        expected=hmac.new(settings.app_secret.encode(),raw.encode(),hashlib.sha256).hexdigest()
        check(hmac.compare_digest(expected,signature),'INVALID_LOCATION','Vị trí không hợp lệ')
        data=json.loads(base64.urlsafe_b64decode(raw))
        check(data['expires']>now().timestamp(),'LOCATION_EXPIRED','Tìm lại địa chỉ để xác nhận vị trí')
        check(-90<=float(data['latitude'])<=90 and -180<=float(data['longitude'])<=180,'INVALID_LOCATION','Tọa độ không hợp lệ')
        return data
    except (ValueError,TypeError,KeyError,AttributeError):
        raise Fault('INVALID_LOCATION','Chọn địa chỉ từ kết quả bản đồ')


async def search(query):
    from .db import text
    query=text(query,200,3)
    data=await goong('v2/place/autocomplete',{'input':query,'limit':5,'location':'20.98,105.79','radius':20})
    return [{'id':p['place_id'],'label':p['description']} for p in data.get('predictions',[])][:5]


async def resolve(place_id):
    from .db import text
    data=await goong('v2/place/detail',{'place_id':text(place_id,512,1)})
    result=data.get('result',{})
    point=result.get('geometry',{}).get('location',{})
    check('lat' in point and 'lng' in point,'LOCATION_NOT_FOUND','Không xác định được vị trí địa chỉ',422)
    location={'latitude':str(point['lat']),'longitude':str(point['lng']),'placeId':place_id,
              'address':result.get('formatted_address') or result.get('name',''),
              'expires':(now()+timedelta(minutes=30)).timestamp()}
    return {**location,'locationToken':location_token(location)}


async def warehouse(s):
    row=await one(s,'system_settings',T['system_settings'].c.setting_key=='warehouse',required=False)
    return {'address':'96A Trần Phú, Hà Đông, Hà Nội','version':'0','configured':False} if not row else {
        **row['value_json'],'version':str(row['version']),'configured':True}


async def save_warehouse(s,user,body):
    from .commerce import audit
    from sqlalchemy import update
    location=verify_location(body.get('locationToken'))
    old=await one(s,'system_settings',T['system_settings'].c.setting_key=='warehouse',required=False,lock=True)
    check(str(old['version'] if old else 0)==str(body.get('expectedVersion')),'VERSION_CONFLICT','Vị trí kho đã đổi',409)
    values={k:location[k] for k in ('latitude','longitude','placeId','address')}
    data=dict(value_json=values,version=old['version']+1 if old else 1,updated_by=user['id'],updated_at=now())
    if old: await s.execute(update(T['system_settings']).where(T['system_settings'].c.setting_key=='warehouse').values(**data))
    else: await add(s,'system_settings',setting_key='warehouse',**data)
    await audit(s,user,'warehouse.update','settings',None,old,values)
    return await warehouse(s)


def fee_for(policy,meters):
    check(policy['distance_enabled'] and all(policy.get(k) is not None for k in ('included_km','extra_km_fee','max_distance_km')),
          'DELIVERY_NOT_CONFIGURED','Người bán cần cấu hình phí giao theo khoảng cách',409)
    check(Decimal(meters)<=policy['max_distance_km']*1000,'OUTSIDE_DELIVERY_AREA','Địa chỉ nằm ngoài phạm vi giao hàng',422)
    extra=max(Decimal(0),Decimal(meters)/1000-policy['included_km'])
    return policy['shipping_fee']+extra.to_integral_value(rounding=ROUND_CEILING)*policy['extra_km_fee']


def cart_hash(items):
    return digest(sorted([{'offerId':i['offerId'],'quantity':format(number(i['quantity']),'f'),
                          'expectedPriceVersion':str(i['expectedPriceVersion'])} for i in items],key=lambda i:i['offerId']))


async def prepare(s,user,body):
    from .commerce import catalog
    addr=await one(s,'addresses',T['addresses'].c.id==uuid(body.get('addressId')),T['addresses'].c.user_id==user['id'],T['addresses'].c.deleted_at==None)
    check(addr['latitude'] is not None and addr['longitude'] is not None,'ADDRESS_LOCATION_REQUIRED','Xác nhận vị trí địa chỉ nhận trên bản đồ',409)
    policy=await one(s,'delivery_policies',T['delivery_policies'].c.group_id==user['group_id'],
        T['delivery_policies'].c.zone_id==addr['zone_id'],T['delivery_policies'].c.method=='INDIVIDUAL',T['delivery_policies'].c.active==True)
    fee_for(policy,0)
    wh=await warehouse(s); check(wh['configured'],'WAREHOUSE_NOT_CONFIGURED','Người bán chưa xác nhận vị trí kho',409)
    items=body.get('items'); check(isinstance(items,list) and 0<len(items)<=20 and all(isinstance(i,dict) for i in items),'INVALID_ITEMS','Giỏ hàng không hợp lệ')
    ids=[uuid(i.get('offerId')) for i in items]; check(len(ids)==len(set(ids)),'DUPLICATE_ITEM','Mặt hàng bị lặp')
    offers={o['id']:o for o in await catalog(s,user,offer_ids=ids)}
    subtotal=Decimal(0)
    from decimal import ROUND_HALF_UP
    for item in items:
        offer=offers.get(item['offerId']); check(offer is not None,'PRODUCT_UNAVAILABLE','Mặt hàng không còn được phép mua',409)
        check(str(offer['price_version'])==str(item.get('expectedPriceVersion')),'REQUOTE_REQUIRED','Giá hàng đã đổi',409)
        quantity=number(item.get('quantity'),minimum=Decimal('.001'))
        check(quantity%Decimal(offer['quantity_step'])==0 and quantity<=Decimal(offer['available_qty']),'INSUFFICIENT_STOCK','Số lượng không hợp lệ hoặc vượt kho',409)
        subtotal+=(quantity*Decimal(offer['unit_price'])).quantize(Decimal(1),rounding=ROUND_HALF_UP)
    check(subtotal>=policy['minimum_subtotal'],'DELIVERY_MINIMUM','Đơn chưa đạt mức tối thiểu')
    return addr,policy,wh,cart_hash(items)


async def route(addr,wh):
    data=await goong('v2/direction',{'origin':wh['latitude']+','+wh['longitude'],
        'destination':str(addr['latitude'])+','+str(addr['longitude']),'vehicle':'bike','alternatives':'false'})
    routes=data.get('routes',[]); check(bool(routes),'ROUTE_NOT_FOUND','Không tìm thấy đường giao tới địa chỉ này',422)
    legs=routes[0].get('legs',[]); check(bool(legs),'ROUTE_NOT_FOUND','Không tìm thấy tuyến giao',422)
    try:
        meters=sum(int(leg['distance']['value']) for leg in legs)
        seconds=sum(int(leg['duration']['value']) for leg in legs)
        check(0<=meters<=10000000 and seconds>=0,'MAP_UNAVAILABLE','Dữ liệu tuyến không hợp lệ',503)
    except (ValueError,KeyError,TypeError): raise Fault('MAP_UNAVAILABLE','Dữ liệu tuyến không hợp lệ',503)
    return meters,seconds,{'polyline':routes[0].get('overview_polyline',{}).get('points','')}


async def record_quote(s,user,prepared,routed):
    addr,policy,wh,fingerprint=prepared
    meters,seconds,route_info=routed
    id=uid(); expires=now()+timedelta(minutes=5)
    fee=fee_for(policy,meters)
    await add(s,'delivery_quotes',id=id,user_id=user['id'],address_id=addr['id'],address_version=addr['version'],group_id=user['group_id'],
        policy_id=policy['id'],policy_version=policy['version'],warehouse_version=int(wh['version']),cart_hash=fingerprint,
        distance_meters=meters,duration_seconds=seconds,shipping_fee=fee,expires_at=expires,created_at=now(),route_json=route_info)
    return public({'id':id,'distanceMeters':meters,'durationSeconds':seconds,'shippingFee':fee,'expiresAt':expires,
                   'warehouseAddress':wh['address'],'destinationAddress':addr['address_line']})


async def validate_quote(s,user,body,address,policy):
    q=await one(s,'delivery_quotes',T['delivery_quotes'].c.id==uuid(body.get('deliveryQuoteId')),T['delivery_quotes'].c.user_id==user['id'])
    wh=await warehouse(s)
    check(q['expires_at']>now() and q['address_id']==address['id'] and q['address_version']==address['version']
        and q['group_id']==user['group_id'] and q['policy_id']==policy['id'] and q['policy_version']==policy['version']
        and q['warehouse_version']==int(wh['version']) and q['cart_hash']==cart_hash(body['items']),
        'REQUOTE_REQUIRED','Địa chỉ, giỏ hàng hoặc phí đã đổi; lấy phí giao mới và xác nhận lại',409)
    return q
