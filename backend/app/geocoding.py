"""Confirmed public addresses, then Photon, with conservative Nominatim fallback."""
import asyncio
import hashlib
import math
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation
import httpx
from . import shipping
from .config import settings
from .db import T, rows, one, add, change, check, text, uid, uuid, now, public, Fault

_lock=asyncio.Lock()
_last_request=0.0
_cache={}
_places={}


def normalize(value):
    value=unicodedata.normalize('NFKD',str(value).casefold().replace('đ','d'))
    value=''.join(c for c in value if not unicodedata.combining(c))
    value=re.sub(r'[^a-z0-9/ -]+',' ',value)
    return ' '.join(value.split())


def house_number(query):
    match=re.match(r'^(?:so\s+)?(\d+[a-z]?(?:[/\-]\d+[a-z]?)*)(?:\s|$)',normalize(query))
    return match.group(1) if match else ''


def street_words(value):
    return set(normalize(value).split())-{'duong','pho','street','road','so'}


def quality(query, place):
    requested=house_number(query)
    if place.get('source')=='LOCAL': return 'VERIFIED'
    if place.get('approximate'): return 'STREET'
    street=street_words(place.get('street',''))
    if requested and normalize(place.get('houseNumber',''))==requested and street and street<=street_words(query):
        return 'HOUSE_NUMBER'
    return 'NEARBY'


def distance_km(point, center):
    lat,lon=float(point['latitude']),float(point['longitude'])
    lat0,lon0=float(center['latitude']),float(center['longitude'])
    x=math.sin(math.radians(lat-lat0)/2)**2+math.cos(math.radians(lat))*math.cos(math.radians(lat0))*math.sin(math.radians(lon-lon0)/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(x)))


def from_photon(feature):
    try:
        p=feature['properties']; lon,lat=feature['geometry']['coordinates'][:2]
        lat,lon=Decimal(str(lat)),Decimal(str(lon))
        check(lat.is_finite() and lon.is_finite() and -90<=lat<=90 and -180<=lon<=180,'LOCATION_NOT_FOUND','Invalid coordinates')
        check(str(p.get('countrycode','VN')).upper()=='VN','LOCATION_NOT_FOUND','Outside Vietnam')
        osm=str(p['osm_type']).upper()[0]; oid=int(p['osm_id'])
        check(osm in 'NWR' and oid>0,'LOCATION_NOT_FOUND','Invalid OSM reference')
        street=str(p.get('street') or '')
        house=str(p.get('housenumber') or '')
        parts=[str(p.get('name') or ''), ' '.join(filter(None,[house,street]))]
        parts += [str(p[k]) for k in ('district','city','state','country') if p.get(k)]
        parts=list(dict.fromkeys(part for part in parts if part))
        approximate=p.get('type') in ('street','locality','city','district','county','state','country') or p.get('osm_key')=='highway'
        return {'id':f'photon:{osm}{oid}','osmId':f'{osm}{oid}', 'source':'PHOTON',
                'address':', '.join(parts)[:500], 'houseNumber':house,'street':street,
                'latitude':str(lat),'longitude':str(lon),'approximate':approximate}
    except (KeyError,TypeError,ValueError,InvalidOperation,IndexError):
        raise Fault('LOCATION_NOT_FOUND','Kết quả Photon không hợp lệ',422)


async def photon_json(query, center):
    global _last_request
    async with _lock:
        delay=1.05-(time.monotonic()-_last_request)
        if delay>0: await asyncio.sleep(delay)
        _last_request=time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=8,trust_env=False,headers={
                'User-Agent':'RealtimeOrders/1.0 (https://github.com/theycallmeheng/RealtimeOrders)',
                'Referer':settings.app_origin}) as client:
                response=await client.get(settings.photon_url.rstrip('/')+'/api/',params={
                    'q':query,'limit':8,'lat':center['latitude'],'lon':center['longitude']})
            if response.status_code in (403,429):
                raise Fault('MAP_RATE_LIMIT','Photon đang giới hạn lượt; hãy đợi rồi thử lại',503)
            check(response.status_code==200,'MAP_UNAVAILABLE','Không kết nối được Photon',503)
            data=response.json()
            check(isinstance(data,dict) and isinstance(data.get('features'),list),'MAP_UNAVAILABLE','Photon trả dữ liệu không hợp lệ',503)
            return data['features']
        except (httpx.HTTPError,ValueError,TypeError):
            raise Fault('MAP_UNAVAILABLE','Không kết nối được Photon; hãy thử lại',503)


async def local_matches(s,query):
    if s is None: return []
    candidates=await rows(s,'verified_locations',T['verified_locations'].c.active==True,limit=2000)
    q=normalize(query); result=[]
    for row in candidates:
        names=[row['label'],*(row['aliases'] or [])]
        if any(q==normalize(name) or (len(q)>=4 and q in normalize(name)) for name in names):
            result.append({'id':'local:'+row['id'],'source':'LOCAL','address':row['label'],
                           'houseNumber':row['house_number'],'street':row['street'],
                           'latitude':str(row['latitude']),'longitude':str(row['longitude']),'approximate':False,
                           'queryExact':any(q==normalize(name) for name in names)})
    return result


async def search(s,query):
    query=text(query,200,3)
    local=await local_matches(s,query)
    center={'latitude':20.9809427,'longitude':105.7870861}
    if s is not None:
        wh=await shipping.warehouse(s)
        if wh['configured']: center={'latitude':float(wh['latitude']),'longitude':float(wh['longitude'])}
    key=hashlib.sha256((normalize(query)+str(center)).encode()).hexdigest()
    exact_local=any(p.get('queryExact') for p in local)
    remote=[] if exact_local else shipping._cache_get(_cache,key)
    if remote is None:
        remote=[]; failures=[]; success=False
        try:
            for item in await photon_json(query,center):
                try: remote.append(from_photon(item))
                except Fault: continue
            success=True
        except Fault as exc: failures.append(exc)
        if not any(quality(query,p)=='HOUSE_NUMBER' for p in remote):
            try:
                data=await shipping.nominatim_json('search',{'q':query,'format':'jsonv2','countrycodes':'vn',
                    'accept-language':'vi','addressdetails':1,'limit':6,
                    'viewbox':f"{center['longitude']-.22},{center['latitude']+.22},{center['longitude']+.22},{center['latitude']-.22}",
                    'bounded':0})
                check(isinstance(data,list),'MAP_UNAVAILABLE','Kết quả tìm địa chỉ không hợp lệ',503)
                for item in data:
                    if not isinstance(item,dict): continue
                    try: place=shipping.normalized_place(item)
                    except Fault: continue
                    address=item.get('address') or {}
                    remote.append({**place,'source':'NOMINATIM','osmId':place['id'],
                        'houseNumber':str(address.get('house_number') or ''),
                        'street':str(address.get('road') or address.get('pedestrian') or '')})
                success=True
            except Fault as exc: failures.append(exc)
        if not success and failures and not local: raise failures[-1]
        # Provider outages must not poison later retries with a cached empty response.
        if not failures: shipping._cache_set(_cache,key,remote,600)
    places=local+(remote or [])
    priority={'VERIFIED':0,'HOUSE_NUMBER':1,'NEARBY':2,'STREET':3}
    places.sort(key=lambda p:(priority[quality(query,p)],distance_km(p,center)))
    results=[];seen=set()
    for place in places:
        identity=place.get('osmId') or place['id']
        if identity in seen or not place['address']: continue
        seen.add(identity)
        match=quality(query,place)
        shipping._cache_set(_places,place['id'],{**place,'matchType':match},3600)
        results.append({'id':place['id'],'label':place['address'],'source':place['source'],'matchType':match,
                        'houseNumber':place['houseNumber'],'street':place['street'],'approximate':place['approximate']})
        if len(results)>=8: break
    return results


async def resolve(s,place_id):
    place_id=text(place_id,80,2)
    if place_id.startswith('local:'):
        row=await one(s,'verified_locations',T['verified_locations'].c.id==uuid(place_id[6:]),T['verified_locations'].c.active==True)
        point={'latitude':str(row['latitude']),'longitude':str(row['longitude']),'address':row['label'],
               'id':place_id,'source':'LOCAL','matchType':'VERIFIED','approximate':False}
    else:
        point=shipping._cache_get(_places,place_id)
        if point is None:
            if re.fullmatch(r'[NWR][0-9]{1,20}',place_id): return await shipping.resolve(place_id)
            check(re.fullmatch(r'photon:[NWR][0-9]{1,20}',place_id) is not None,'INVALID_LOCATION','Mã địa điểm không hợp lệ')
            raise Fault('LOCATION_EXPIRED','Kết quả đã hết hạn. Tìm lại địa chỉ.',409)
    data={'latitude':point['latitude'],'longitude':point['longitude'],'placeId':point['id'],
          'address':point['address'],'expires':(now()+shipping.timedelta(minutes=30)).timestamp()}
    return {**data,'locationToken':shipping.location_token(data),'source':point.get('source'),
            'matchType':point.get('matchType','NEARBY'),'approximate':point.get('approximate',False)}


async def save_verified(s,user,id,body,delete=False):
    from .commerce import version,audit
    from .events import emit
    old=await one(s,'verified_locations',T['verified_locations'].c.id==id,lock=True) if id else None
    if old: version(old,body)
    if delete:
        values={'active':False}
    else:
        label=text(body.get('label'),500,3)
        aliases=body.get('aliases',[])
        check(isinstance(aliases,list) and len(aliases)<=20,'INVALID_ALIASES','Tối đa 20 tên gọi khác')
        aliases=list(dict.fromkeys(text(a,200,3) for a in aliases))
        token=body.get('locationToken')
        loc=shipping.verify_location(token) if token else old
        check(loc is not None,'LOCATION_REQUIRED','Chọn và xác nhận ghim trước khi lưu')
        values={'label':label,'aliases':aliases,'house_number':text(body.get('houseNumber',''),40),
                'street':text(body.get('street',''),200),'latitude':loc['latitude'],'longitude':loc['longitude'],'active':True}
    values.update(updated_by=user['id'],updated_at=now())
    id=id or uid()
    if old: await change(s,'verified_locations',id,version=old['version']+1,**values)
    else: await add(s,'verified_locations',id=id,version=1,created_at=now(),**values)
    await audit(s,user,'verified_location.update','verified_location',id,old,values)
    emit(s,'admin:ops','CONFIG_CHANGED',{'table':'verified_locations','id':id})
    return public(await one(s,'verified_locations',T['verified_locations'].c.id==id))
