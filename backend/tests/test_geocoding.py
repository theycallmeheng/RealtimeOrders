from unittest.mock import AsyncMock,patch
import pytest
from app import geocoding as geo,shipping
from app.db import Fault


def feature(house='334',street='Đường Nguyễn Trãi',oid=1,kind='house',lng=105.808):
    return {'properties':{'osm_type':'W','osm_id':oid,'countrycode':'VN','housenumber':house,
            'street':street,'name':'Public test place','city':'Hà Nội','type':kind},
            'geometry':{'coordinates':[lng,20.996]}}

@pytest.fixture(autouse=True)
def clear_cache():
    geo._cache.clear();geo._places.clear()
    yield
    geo._cache.clear();geo._places.clear()


def test_normalize_unicode_house_and_alley():
    assert geo.normalize('Số 96A, Đường Trần Phú')=='so 96a duong tran phu'
    assert geo.house_number('Số 17/2A, Nguyễn Trãi')=='17/2a'
    assert geo.house_number('Ngõ 17 Trần Phú')==''

@pytest.mark.parametrize('query,house,street,kind,expected',[
    ('334 Nguyen Trai Ha Noi','334','Đường Nguyễn Trãi','house','HOUSE_NUMBER'),
    ('334 Nguyen Trai Ha Noi','334','Trần Phú','house','NEARBY'),
    ('334 Nguyen Trai Ha Noi','33','Nguyễn Trãi','house','NEARBY'),
    ('96A Tran Phu','','Trần Phú','street','STREET'),
])
def test_quality_never_invents_house_match(query,house,street,kind,expected):
    assert geo.quality(query,geo.from_photon(feature(house,street,kind=kind)))==expected


async def test_verified_local_prevents_external_lookup():
    point={'id':'local:test','source':'LOCAL','address':'96A Trần Phú','houseNumber':'96A',
           'street':'Trần Phú','latitude':'20.98','longitude':'105.78','approximate':False,'queryExact':True}
    with patch.object(geo,'local_matches',AsyncMock(return_value=[point])),patch.object(geo,'photon_json',AsyncMock()) as remote:
        result=await geo.search(None,'96A Tran Phu')
        assert result[0]['matchType']=='VERIFIED'
        remote.assert_not_awaited()


async def test_exact_photon_skips_fallback_and_uses_cached_coordinates():
    with patch.object(geo,'photon_json',AsyncMock(return_value=[feature()])) as photon,patch.object(shipping,'nominatim_json',AsyncMock()) as fallback:
        result=await geo.search(None,'334 Nguyen Trai Ha Noi')
        again=await geo.search(None,'334 Nguyen Trai Ha Noi')
        assert result==again and result[0]['matchType']=='HOUSE_NUMBER'
        assert photon.await_count==1;fallback.assert_not_awaited()
        point=await geo.resolve(None,result[0]['id'])
        assert point['longitude']=='105.808'
        assert shipping.verify_location(point['locationToken'])['placeId']=='photon:W1'


async def test_street_result_falls_back_and_prefers_house_match():
    fallback=[{'osm_type':'way','osm_id':2,'lat':'20.99','lon':'105.8','display_name':'334 Nguyen Trai',
               'address':{'house_number':'334','road':'Nguyễn Trãi'}}]
    with patch.object(geo,'photon_json',AsyncMock(return_value=[feature('',kind='street')])),patch.object(shipping,'nominatim_json',AsyncMock(return_value=fallback)):
        result=await geo.search(None,'334 Nguyen Trai')
        assert result[0]['source']=='NOMINATIM' and result[0]['matchType']=='HOUSE_NUMBER'
        assert result[-1]['matchType']=='STREET'


async def test_provider_failure_fallback_and_no_cache_poisoning():
    fail=Fault('MAP_UNAVAILABLE','Unavailable',503)
    with patch.object(geo,'photon_json',AsyncMock(side_effect=fail)),patch.object(shipping,'nominatim_json',AsyncMock(return_value=[])):
        assert await geo.search(None,'Public test street')==[]
        assert not geo._cache
    with patch.object(geo,'photon_json',AsyncMock(side_effect=fail)),patch.object(shipping,'nominatim_json',AsyncMock(side_effect=fail)):
        with pytest.raises(Fault): await geo.search(None,'Public test street')


async def test_expired_photon_id_requires_new_search():
    with pytest.raises(Fault) as error: await geo.resolve(None,'photon:W123')
    assert error.value.code=='LOCATION_EXPIRED'


async def test_dedupe_same_osm_object():
    nom={'osm_type':'way','osm_id':1,'lat':'20.996','lon':'105.808','display_name':'Same test street','class':'highway'}
    with patch.object(geo,'photon_json',AsyncMock(return_value=[feature('',kind='street')])),patch.object(shipping,'nominatim_json',AsyncMock(return_value=[nom])):
        result=await geo.search(None,'Public test street')
        assert len(result)==1


async def test_partial_local_match_still_searches_provider():
    point={'id':'local:test','source':'LOCAL','address':'334 Nguyen Trai','houseNumber':'334',
           'street':'Nguyen Trai','latitude':'20.99','longitude':'105.8','approximate':False,'queryExact':False}
    with patch.object(geo,'local_matches',AsyncMock(return_value=[point])),patch.object(geo,'photon_json',AsyncMock(return_value=[feature()])) as remote:
        result=await geo.search(None,'334 Nguyen Trai')
        assert len(result)==2 and result[0]['source']=='LOCAL'
        remote.assert_awaited_once()
