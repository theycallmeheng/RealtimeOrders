"""OpenStreetMap geocoding and OSRM routing adapters."""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import httpx
from .config import settings
from .db import T, now, uid, uuid, one, add, check, number, digest, public, Fault


NOMINATIM_URL = settings.nominatim_url.rstrip("/")
OSRM_URL = settings.osrm_url.rstrip("/")
_MIN_PUBLIC_REQUEST_INTERVAL = 1.05
_nominatim_lock = asyncio.Lock()
_osrm_lock = asyncio.Lock()
_nominatim_last_request = 0.0
_osrm_last_request = 0.0
_search_cache = {}
_place_cache = {}
_route_cache = {}


def _cache_get(cache, key):
    entry = cache.get(key)
    if entry is None:
        return None
    expires, value = entry
    if expires <= time.monotonic():
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache, key, value, ttl):
    if len(cache) >= 512:
        for item, (expires, _) in list(cache.items()):
            if expires <= time.monotonic():
                cache.pop(item, None)
        while len(cache) >= 512:
            cache.pop(next(iter(cache)))
    cache[key] = (time.monotonic() + ttl, value)


async def nominatim_json(endpoint, params):
    """Call the public Nominatim service at no more than one request per second."""
    global _nominatim_last_request
    async with _nominatim_lock:
        delay = _MIN_PUBLIC_REQUEST_INTERVAL - (time.monotonic() - _nominatim_last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        _nominatim_last_request = time.monotonic()
        try:
            headers = {
                "User-Agent": "RealtimeOrders/1.0 (https://github.com/theycallmeheng/RealtimeOrders)",
                "Referer": settings.app_origin,
            }
            async with httpx.AsyncClient(timeout=10, trust_env=False, headers=headers) as client:
                response = await client.get(f"{NOMINATIM_URL}/{endpoint}", params=params)
            if response.status_code == 404:
                return []
            if response.status_code in (403, 429):
                raise Fault("MAP_RATE_LIMIT", "Dịch vụ tìm địa chỉ đang giới hạn lượt; vui lòng đợi rồi thử lại", 503)
            check(response.status_code == 200, "MAP_UNAVAILABLE", "OpenStreetMap đang bận; hãy thử lại sau", 503)
            return response.json()
        except Fault:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise Fault("MAP_UNAVAILABLE", "Không kết nối được OpenStreetMap; hãy kiểm tra mạng và thử lại", 503)


async def osrm_json(url, params):
    """Call the public OSRM demo service at no more than one request per second."""
    global _osrm_last_request
    async with _osrm_lock:
        delay = _MIN_PUBLIC_REQUEST_INTERVAL - (time.monotonic() - _osrm_last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        _osrm_last_request = time.monotonic()
        try:
            headers = {
                "User-Agent": "RealtimeOrders/1.0 (https://github.com/theycallmeheng/RealtimeOrders)",
                "Referer": settings.app_origin,
            }
            async with httpx.AsyncClient(timeout=10, trust_env=False, headers=headers) as client:
                response = await client.get(url, params=params)
            if response.status_code in (403, 429):
                raise Fault("MAP_RATE_LIMIT", "Dịch vụ tính tuyến đang giới hạn lượt; vui lòng đợi rồi thử lại", 503)
            check(response.status_code == 200, "MAP_UNAVAILABLE", "OSRM đang bận; hãy thử lại sau", 503)
            data = response.json()
            check(isinstance(data, dict), "MAP_UNAVAILABLE", "OSRM trả dữ liệu không hợp lệ", 503)
            return data
        except Fault:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise Fault("MAP_UNAVAILABLE", "Không kết nối được OSRM; hãy kiểm tra mạng và thử lại", 503)


def osm_type_prefix(osm_type):
    return {"node": "N", "way": "W", "relation": "R"}.get(osm_type)


def normalized_place(item):
    prefix = osm_type_prefix(item.get("osm_type"))
    osm_id = item.get("osm_id")
    try:
        latitude = Decimal(str(item["lat"]))
        longitude = Decimal(str(item["lon"]))
        check(-90 <= latitude <= 90 and -180 <= longitude <= 180,
              "LOCATION_NOT_FOUND", "Không xác định được vị trí địa chỉ", 422)
        check(prefix is not None and int(osm_id) > 0,
              "LOCATION_NOT_FOUND", "Kết quả địa chỉ không hợp lệ", 422)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise Fault("LOCATION_NOT_FOUND", "Không xác định được vị trí địa chỉ", 422)
    place_id = f"{prefix}{int(osm_id)}"
    return {
        "id": place_id,
        "latitude": str(latitude),
        "longitude": str(longitude),
        "address": str(item.get("display_name") or "")[:500],
        "approximate": item.get("category", item.get("class")) in ("highway", "boundary") or item.get("type") in ("road", "administrative"),
    }


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


async def search(s, query):
    from .db import text
    query = text(query, 200, 3)
    cache_key = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
    cached = _cache_get(_search_cache, cache_key)
    if cached is not None:
        return cached

    data = await nominatim_json("search", {
        "q": query, "format": "jsonv2", "countrycodes": "vn",
        "accept-language": "vi", "addressdetails": 0, "limit": 5,
    })
    check(isinstance(data, list), "MAP_UNAVAILABLE", "OpenStreetMap trả danh sách địa chỉ không hợp lệ", 503)
    results = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            place = normalized_place(item)
        except Fault:
            continue
        _cache_set(_place_cache, place["id"], place, 3600)
        if place["address"]:
            results.append({"id": place["id"], "label": place["address"], **({"approximate": True} if place["approximate"] else {})})
    _cache_set(_search_cache, cache_key, results, 600)
    return results


async def resolve(place_id):
    from .db import text
    place_id = text(place_id, 40, 2)
    check(re.fullmatch(r"[NWR][0-9]{1,20}", place_id) is not None,
          "INVALID_LOCATION", "Chọn địa chỉ từ kết quả OpenStreetMap")
    place = _cache_get(_place_cache, place_id)
    if place is None:
        data = await nominatim_json("lookup", {
            "osm_ids": place_id, "format": "jsonv2",
            "accept-language": "vi", "addressdetails": 0,
        })
        check(isinstance(data, list), "MAP_UNAVAILABLE", "OpenStreetMap trả dữ liệu địa chỉ không hợp lệ", 503)
        check(bool(data), "LOCATION_NOT_FOUND", "Không tìm thấy địa chỉ trên OpenStreetMap", 422)
        place = normalized_place(data[0])
        _cache_set(_place_cache, place_id, place, 3600)

    location = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "placeId": place["id"],
        "address": place["address"],
        "expires": (now() + timedelta(minutes=30)).timestamp(),
    }
    return {**location, "approximate": place.get("approximate", False), "locationToken": location_token(location)}


def pin_location(body):
    from .db import text
    try:
        lat,lon=Decimal(str(body.get('latitude'))),Decimal(str(body.get('longitude')))
    except (InvalidOperation,ValueError,TypeError):
        raise Fault('INVALID_LOCATION','Chọn một điểm hợp lệ trên bản đồ')
    check(lat.is_finite() and lon.is_finite() and -90<=lat<=90 and -180<=lon<=180,
          'INVALID_LOCATION','Tọa độ không hợp lệ')
    latitude,longitude=format(lat.quantize(Decimal('.0000001')),'f'),format(lon.quantize(Decimal('.0000001')),'f')
    location={'latitude':latitude,'longitude':longitude,'placeId':f'pin:{latitude},{longitude}',
              'address':text(body.get('address') or 'Điểm nhận đã chọn trên bản đồ',500,1),
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
    try: distance=Decimal(str(meters))
    except (InvalidOperation,ValueError): raise Fault('INVALID_DISTANCE','Khoảng cách không hợp lệ')
    check(distance.is_finite() and distance>=0,'INVALID_DISTANCE','Khoảng cách không hợp lệ')
    mode=policy.get('pricing_mode','BASE_PLUS_EXTRA')
    check(mode in ('BASE_PLUS_EXTRA','TIERED_KM'),'DELIVERY_NOT_CONFIGURED','Cách tính phí giao chưa hợp lệ',409)
    required=('included_km','extra_km_fee') + (('per_km_fee',) if mode=='TIERED_KM' else ('max_distance_km',))
    check(policy['distance_enabled'] and all(policy.get(k) is not None for k in required),
          'DELIVERY_NOT_CONFIGURED','Người bán cần cấu hình phí giao theo khoảng cách',409)
    maximum=policy.get('max_distance_km')
    check(maximum is None or distance<=Decimal(str(maximum))*1000,
          'OUTSIDE_DELIVERY_AREA','Địa chỉ nằm ngoài phạm vi giao hàng',422)
    km=distance/1000
    threshold=Decimal(str(policy['included_km']))
    if mode=='TIERED_KM':
        rounding=policy.get('distance_rounding','EXACT')
        check(rounding in ('EXACT','CEIL_KM'),'DELIVERY_NOT_CONFIGURED','Cách làm tròn km chưa hợp lệ',409)
        if rounding=='CEIL_KM': km=km.to_integral_value(rounding=ROUND_CEILING)
        fee=(Decimal(str(policy['shipping_fee'])) + min(km,threshold)*Decimal(str(policy['per_km_fee']))
             + max(Decimal(0),km-threshold)*Decimal(str(policy['extra_km_fee'])))
        step=Decimal(str(policy.get('fee_rounding_step',1)))
        check(step.is_finite() and step>=1 and step==step.to_integral_value(),'DELIVERY_NOT_CONFIGURED','Bước làm tròn phí không hợp lệ',409)
        return (fee/step).to_integral_value(rounding=ROUND_CEILING)*step
    extra=max(Decimal(0),km-threshold)
    return policy['shipping_fee']+extra.to_integral_value(rounding=ROUND_CEILING)*policy['extra_km_fee']


def cart_hash(items):
    return digest(sorted([{'offerId':i['offerId'],'quantity':format(number(i['quantity']),'f'),
                          'expectedPriceVersion':str(i['expectedPriceVersion'])} for i in items],key=lambda i:i['offerId']))


async def prepare(s,user,body):
    from .commerce import catalog
    address_id=uuid(body.get('addressId'))
    addr=await one(s,'addresses',T['addresses'].c.id==address_id,T['addresses'].c.user_id==user['id'],T['addresses'].c.deleted_at==None)
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


async def route(addr, wh):
    try:
        origin_lat, origin_lng = float(wh["latitude"]), float(wh["longitude"])
        destination_lat, destination_lng = float(addr["latitude"]), float(addr["longitude"])
    except (ValueError, TypeError, KeyError, OverflowError):
        raise Fault("MAP_UNAVAILABLE", "Tọa độ kho hoặc địa chỉ không hợp lệ", 503)
    check(-90 <= origin_lat <= 90 and -180 <= origin_lng <= 180
          and -90 <= destination_lat <= 90 and -180 <= destination_lng <= 180,
          "MAP_UNAVAILABLE", "Tọa độ kho hoặc địa chỉ không hợp lệ", 503)

    cache_key = tuple(round(value, 6) for value in (origin_lat, origin_lng, destination_lat, destination_lng))
    cached = _cache_get(_route_cache, cache_key)
    if cached is not None:
        return cached

    coordinates = f"{origin_lng:.7f},{origin_lat:.7f};{destination_lng:.7f},{destination_lat:.7f}"
    data = await osrm_json(f"{OSRM_URL}/route/v1/driving/{coordinates}", {
        "overview": "false", "steps": "false", "alternatives": "false",
    })
    routes = data.get("routes") or []
    check(data.get("code") == "Ok" and bool(routes),
          "ROUTE_NOT_FOUND", "Không tìm thấy tuyến đường tới địa chỉ này", 422)
    try:
        result = routes[0]
        meters = int(Decimal(str(result["distance"])).to_integral_value(rounding=ROUND_CEILING))
        seconds = int(Decimal(str(result["duration"])).to_integral_value(rounding=ROUND_CEILING))
        check(0 <= meters <= 10000000 and seconds >= 0,
              "MAP_UNAVAILABLE", "Dữ liệu tuyến không hợp lệ", 503)
    except (ValueError, KeyError, TypeError, InvalidOperation):
        raise Fault("MAP_UNAVAILABLE", "Dữ liệu tuyến không hợp lệ", 503)

    routed = (meters, seconds, {"provider": "OSRM", "profile": "driving"})
    _cache_set(_route_cache, cache_key, routed, 600)
    return routed

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
    quote_id=uuid(body.get('deliveryQuoteId'))
    q=await one(s,'delivery_quotes',T['delivery_quotes'].c.id==quote_id,T['delivery_quotes'].c.user_id==user['id'])
    wh=await warehouse(s)
    check(q['expires_at']>now() and q['address_id']==address['id'] and q['address_version']==address['version']
        and q['group_id']==user['group_id'] and q['policy_id']==policy['id'] and q['policy_version']==policy['version']
        and q['warehouse_version']==int(wh['version']) and q['cart_hash']==cart_hash(body['items']),
        'REQUOTE_REQUIRED','Địa chỉ, giỏ hàng hoặc phí đã đổi; lấy phí giao mới và xác nhận lại',409)
    return q
