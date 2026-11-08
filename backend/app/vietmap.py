"""VIETMAP search and routing on the server."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from datetime import timedelta
import httpx
from .config import settings
from .db import Fault, check, now
from .shipping import location_token

async def request(endpoint, params):
    check(bool(settings.vietmap_api_key), 'MAP_NOT_CONFIGURED', 'Chưa cấu hình VIETMAP Services API key', 503)
    try:
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            response = await client.get('https://maps.vietmap.vn/api/' + endpoint,
                params=[('apikey', settings.vietmap_api_key), *params])
        if response.status_code in (401, 403):
            raise Fault('MAP_CONFIG_ERROR', 'VIETMAP từ chối key. Kiểm tra Services key và quyền API.', 503)
        if response.status_code in (423, 429):
            raise Fault('MAP_RATE_LIMIT', 'VIETMAP hết hạn mức hoặc API chưa được bật.', 503)
        check(response.status_code == 200, 'MAP_UNAVAILABLE', 'VIETMAP không thể xử lý yêu cầu.', 503)
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise Fault('MAP_UNAVAILABLE', 'Không kết nối được VIETMAP. Vui lòng thử lại.', 503)

async def search(query):
    data = await request('autocomplete/v4', [('text', query), ('focus', '20.9809427,105.7870861'), ('display_type', '5')])
    check(isinstance(data, list), 'MAP_UNAVAILABLE', 'Kết quả tìm kiếm VIETMAP không hợp lệ.', 503)
    results = []
    for item in data[:10]:
        if not isinstance(item, dict):
            continue
        ref = item.get('ref_id')
        label = item.get('display')
        if isinstance(ref, str) and len(ref) <= 900 and ref.startswith(('auto:', 'geocode:')) and isinstance(label, str) and label:
            results.append({'id': 'vietmap:' + ref, 'label': label[:500], 'source': 'VIETMAP',
                            'matchType': 'NEARBY', 'approximate': False})
    return results

async def resolve(ref):
    check(isinstance(ref, str) and 6 < len(ref) <= 900 and ref.startswith(('auto:', 'geocode:')) and all(ord(c) >= 33 for c in ref),
          'INVALID_LOCATION', 'Mã địa điểm không hợp lệ')
    data = await request('place/v4', [('refid', ref)])
    try:
        lat = Decimal(str(data['lat']))
        lng = Decimal(str(data['lng']))
        address = data['display']
        check(lat.is_finite() and lng.is_finite() and -90 <= lat <= 90 and -180 <= lng <= 180 and isinstance(address, str) and bool(address),
              'MAP_UNAVAILABLE', 'Kết quả địa điểm VIETMAP không hợp lệ.', 503)
        point = {'latitude': str(lat), 'longitude': str(lng), 'placeId': 'vietmap:' + ref,
                 'address': address[:500], 'expires': (now() + timedelta(minutes=30)).timestamp()}
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise Fault('MAP_UNAVAILABLE', 'Kết quả địa điểm VIETMAP không hợp lệ.', 503)
    return {**point, 'locationToken': location_token(point), 'source': 'VIETMAP', 'matchType': 'NEARBY', 'approximate': False}

async def route(origin_lat, origin_lng, destination_lat, destination_lng):
    data = await request('route/v4', [('point', f'{origin_lat},{origin_lng}'),
        ('point', f'{destination_lat},{destination_lng}'), ('vehicle', 'motorcycle')])
    check(isinstance(data, dict), 'MAP_UNAVAILABLE', 'Kết quả tuyến VIETMAP không hợp lệ.', 503)
    paths = data.get('paths') or []
    check(data.get('code') == 'OK' and bool(paths), 'ROUTE_NOT_FOUND', 'Không tìm thấy tuyến đường tới địa chỉ này.', 422)
    try:
        meters = int(Decimal(str(paths[0]['distance'])).to_integral_value(rounding=ROUND_CEILING))
        seconds = int((Decimal(str(paths[0]['time'])) / 1000).to_integral_value(rounding=ROUND_CEILING))
        check(0 <= meters <= 10000000 and 0 <= seconds <= 10000000, 'MAP_UNAVAILABLE', 'Dữ liệu tuyến không hợp lệ.', 503)
    except (KeyError, IndexError, TypeError, ValueError, InvalidOperation, OverflowError):
        raise Fault('MAP_UNAVAILABLE', 'Dữ liệu tuyến VIETMAP không hợp lệ.', 503)
    return meters, seconds, {'provider': 'VIETMAP', 'profile': 'motorcycle'}
