"""Google Places and Routes adapters. Credentials remain on the server."""
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.parse import quote
import httpx
from .config import settings
from .db import Fault, check, now
from .shipping import location_token, timedelta

async def request(method, url, fields, body=None):
    check(bool(settings.google_maps_server_key), 'MAP_NOT_CONFIGURED', 'Chưa cấu hình khóa Google Maps trên server', 503)
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.request(method, url, json=body, headers={
                'X-Goog-Api-Key': settings.google_maps_server_key, 'X-Goog-FieldMask': fields,
            })
        if response.status_code in (401, 403):
            raise Fault('MAP_CONFIG_ERROR', 'Google Maps từ chối yêu cầu. Kiểm tra billing, API và giới hạn key.', 503)
        if response.status_code == 429:
            raise Fault('MAP_RATE_LIMIT', 'Google Maps đang giới hạn lượt. Hãy thử lại sau.', 503)
        check(response.status_code == 200, 'MAP_UNAVAILABLE', 'Không lấy được dữ liệu Google Maps', 503)
        data = response.json()
        check(isinstance(data, dict), 'MAP_UNAVAILABLE', 'Dữ liệu Google Maps không hợp lệ', 503)
        return data
    except (httpx.HTTPError, ValueError):
        raise Fault('MAP_UNAVAILABLE', 'Không kết nối được Google Maps', 503)

async def search(query):
    data = await request('POST', 'https://places.googleapis.com/v1/places:searchText',
        'places.id,places.formattedAddress',
        {'textQuery': query, 'languageCode': 'vi', 'regionCode': 'VN', 'pageSize': 8})
    return [{'id': 'google:'+p['id'], 'label': p['formattedAddress'], 'source': 'GOOGLE',
             'matchType': 'NEARBY', 'approximate': False}
            for p in data.get('places', []) if isinstance(p, dict) and p.get('id') and p.get('formattedAddress')]

async def resolve(place_id):
    check(re.fullmatch(r'[A-Za-z0-9_-]{1,200}', place_id) is not None, 'INVALID_LOCATION', 'Mã địa điểm không hợp lệ')
    data = await request('GET', 'https://places.googleapis.com/v1/places/'+quote(place_id, safe=''),
                         'id,formattedAddress,location')
    try:
        lat, lng = float(data['location']['latitude']), float(data['location']['longitude'])
        check(-90 <= lat <= 90 and -180 <= lng <= 180, 'MAP_UNAVAILABLE', 'Tọa độ không hợp lệ', 503)
        point = {'latitude': str(lat), 'longitude': str(lng), 'placeId': 'google:'+place_id,
                 'address': data['formattedAddress'], 'expires': (now()+timedelta(minutes=30)).timestamp()}
    except (KeyError, TypeError, ValueError):
        raise Fault('MAP_UNAVAILABLE', 'Dữ liệu địa điểm không hợp lệ', 503)
    return {**point, 'locationToken': location_token(point), 'source': 'GOOGLE', 'matchType': 'NEARBY', 'approximate': False}

async def route(origin_lat, origin_lng, destination_lat, destination_lng):
    data = await request('POST', 'https://routes.googleapis.com/directions/v2:computeRoutes',
        'routes.distanceMeters,routes.duration',
        {'origin': {'location': {'latLng': {'latitude': origin_lat, 'longitude': origin_lng}}},
         'destination': {'location': {'latLng': {'latitude': destination_lat, 'longitude': destination_lng}}},
         'travelMode': 'DRIVE', 'languageCode': 'vi-VN'})
    routes = data.get('routes') or []
    check(bool(routes), 'ROUTE_NOT_FOUND', 'Không tìm thấy tuyến đường tới địa chỉ này', 422)
    try:
        meters = int(routes[0]['distanceMeters'])
        duration = routes[0]['duration']
        check(isinstance(duration, str) and duration.endswith('s'), 'MAP_UNAVAILABLE', 'Thời gian tuyến không hợp lệ', 503)
        seconds = int(Decimal(duration[:-1]).to_integral_value(rounding=ROUND_CEILING))
        check(0 <= meters <= 10000000 and seconds >= 0, 'MAP_UNAVAILABLE', 'Dữ liệu tuyến không hợp lệ', 503)
    except (ValueError, TypeError, KeyError, InvalidOperation):
        raise Fault('MAP_UNAVAILABLE', 'Dữ liệu tuyến không hợp lệ', 503)
    return meters, seconds, {'provider': 'GOOGLE', 'profile': 'driving'}
