from unittest.mock import AsyncMock, patch
import pytest
from app import vietmap, shipping, geocoding
from app.db import Fault

async def test_search_resolve_and_signed_location():
    with patch.object(vietmap, 'request', AsyncMock(side_effect=[
        [{'ref_id': 'auto:abc_123', 'display': '140 Trần Phú, Hà Đông'}],
        {'display': '140 Trần Phú, Hà Đông', 'lat': 20.976, 'lng': 105.782},
    ])) as request:
        result = await vietmap.search('140 Trần Phú')
        assert result[0]['id'] == 'vietmap:auto:abc_123'
        point = await vietmap.resolve('auto:abc_123')
        assert shipping.verify_location(point['locationToken'])['latitude'] == '20.976'
        assert request.await_args_list[1].args[1] == [('refid', 'auto:abc_123')]

async def test_route_converts_milliseconds_and_motorcycle():
    with patch.object(vietmap, 'request', AsyncMock(return_value={
        'code': 'OK', 'paths': [{'distance': 2300.4, 'time': 120501}]
    })) as request:
        assert await vietmap.route(21, 105, 21.1, 105.1) == (2301, 121, {'provider': 'VIETMAP', 'profile': 'motorcycle'})
        assert request.await_args.args[1] == [('point', '21,105'), ('point', '21.1,105.1'), ('vehicle', 'motorcycle')]

async def test_errors_and_provider_dispatch():
    with patch.object(vietmap, 'request', AsyncMock(return_value={'code': 'ERROR', 'paths': []})):
        with pytest.raises(Fault) as error:
            await vietmap.route(21, 105, 21.1, 105.1)
        assert error.value.code == 'ROUTE_NOT_FOUND'
    with patch.object(vietmap.settings, 'vietmap_api_key', ''):
        with pytest.raises(Fault) as error:
            await vietmap.search('Hà Đông')
        assert error.value.code == 'MAP_NOT_CONFIGURED'
    with patch.object(geocoding.settings, 'map_provider', 'vietmap'), patch.object(vietmap, 'search', AsyncMock(return_value=[])):
        assert await geocoding.search(None, 'Hà Đông') == []
