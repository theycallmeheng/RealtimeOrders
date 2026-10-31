from unittest.mock import patch
from datetime import timedelta
import pytest
from app import shipping
from app.db import Fault, now


def test_map_pin_preserves_selected_coordinates_and_local_address():
    result=shipping.pin_location({'latitude':'20.98094271','longitude':'105.78708611','address':'Public test landmark'})
    decoded=shipping.verify_location(result['locationToken'])
    assert decoded['latitude']=='20.9809427' and decoded['longitude']=='105.7870861'
    assert decoded['address']=='Public test landmark' and decoded['placeId'].startswith('pin:')
    assert decoded['expires']>now().timestamp()

@pytest.mark.parametrize('lat,lon',[(91,105),(20,181),('NaN',105),(20,'Infinity'),('invalid',105),(None,105)])
def test_map_pin_rejects_invalid_coordinates(lat,lon):
    with pytest.raises(Fault) as error: shipping.pin_location({'latitude':lat,'longitude':lon})
    assert error.value.code=='INVALID_LOCATION'


def test_map_pin_signature_and_expiry():
    token=shipping.pin_location({'latitude':20,'longitude':105})['locationToken']
    with pytest.raises(Fault): shipping.verify_location(token+'x')
    with patch.object(shipping,'now',return_value=now()+timedelta(minutes=31)):
        with pytest.raises(Fault) as error: shipping.verify_location(token)
        assert error.value.code=='LOCATION_EXPIRED'


def test_street_result_is_marked_approximate():
    place=shipping.normalized_place({'osm_type':'way','osm_id':1,'lat':'20','lon':'105','display_name':'Public test street','class':'highway','type':'residential'})
    assert place['approximate'] is True
