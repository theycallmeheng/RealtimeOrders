from decimal import Decimal
import pytest
from app.shipping import fee_for
from app.db import Fault


def policy(first=3000, extra=4000, rounding='EXACT', maximum=None):
    return {'distance_enabled':True, 'pricing_mode':'TIERED_KM', 'per_km_fee':Decimal(first),
            'shipping_fee':Decimal(0), 'included_km':Decimal(10), 'extra_km_fee':Decimal(extra),
            'distance_rounding':rounding, 'max_distance_km':maximum}

@pytest.mark.parametrize('meters,student,worker', [(0,0,0),(2300,6900,8050),(10000,30000,35000),(10001,30004,35005),(12500,40000,47500)])
def test_exact_tiers(meters, student, worker):
    assert fee_for(policy(), meters)==student
    assert fee_for(policy(3500,5000), meters)==worker

@pytest.mark.parametrize('meters,student,worker', [(2300,9000,10500),(10000,30000,35000),(10001,34000,40000),(12500,42000,50000)])
def test_ceiling_tiers(meters, student, worker):
    assert fee_for(policy(rounding='CEIL_KM'), meters)==student
    assert fee_for(policy(3500,5000,'CEIL_KM'), meters)==worker

@pytest.mark.parametrize('rounding',['EXACT','CEIL_KM'])
def test_maximum_is_checked_before_rounding(rounding):
    p=policy(rounding=rounding,maximum=Decimal(10))
    assert fee_for(p,10000)==30000
    with pytest.raises(Fault) as error: fee_for(p,10001)
    assert error.value.code=='OUTSIDE_DELIVERY_AREA'

@pytest.mark.parametrize('meters',[-1,'NaN','Infinity','invalid'])
def test_invalid_distance(meters):
    with pytest.raises(Fault): fee_for(policy(),meters)


@pytest.mark.parametrize('meters,student,worker', [(0,0,0),(2300,7000,9000),(10000,30000,35000),(10001,31000,36000),(12500,40000,48000),(15000,50000,60000)])
def test_configured_thousand_rounding(meters,student,worker):
    for first,extra,expected in [(3000,4000,student),(3500,5000,worker)]:
        p={**policy(first,extra,maximum=Decimal(15)), 'fee_rounding_step':Decimal(1000)}
        assert fee_for(p,meters)==expected

@pytest.mark.parametrize('amount,expected', [(0,0),(6000,6000),(6100,7000),(6800,7000),(7000,7000)])
def test_round_total_up_to_thousand(amount,expected):
    p={**policy(), 'shipping_fee':Decimal(amount),'fee_rounding_step':Decimal(1000)}
    assert fee_for(p,0)==expected

def test_configured_fifteen_km_limit():
    p={**policy(maximum=Decimal(15)), 'fee_rounding_step':Decimal(1000)}
    assert fee_for(p,15000)==50000
    with pytest.raises(Fault) as error: fee_for(p,15001)
    assert error.value.code=='OUTSIDE_DELIVERY_AREA'
