from decimal import Decimal
import pytest
from app.db import number,uuid,text,Fault,public
from app.auth import phone,email
from app.admin import date_time

@pytest.mark.parametrize('value',['NaN','Infinity','-1','0.0001','abc',None])
def test_invalid_decimal(value):
    with pytest.raises(Fault):number(value)

def test_decimal_and_version_wire():
    assert number('0.300')==Decimal('.3')
    assert public({'version':2**60,'quantity':Decimal('.100'),'unit_price':Decimal('28000')})=={'version':str(2**60),'quantity':'0.100','unit_price':'28000'}

def test_identity_normalization_and_uuid():
    assert phone('0900 000 001')=='+84900000001'
    assert email(' Abc@Example.com ')=='abc@example.com'
    with pytest.raises(Fault):uuid('../../private')

def test_timezone_offset_conversion():
    assert date_time('2026-10-22T17:00:00+07:00').hour==10
