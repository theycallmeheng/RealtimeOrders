from datetime import datetime
import pytest
from app.activity import date_range
from app.db import Fault

def test_inclusive_vietnam_day_range():
    start,end=date_range('2026-10-31','2026-10-31')
    assert start==datetime(2026,10,30,17) and end==datetime(2026,10,31,17)

def test_month_and_leap_day_boundaries():
    a,b=date_range('2024-02-29','2024-03-01')
    assert a==datetime(2024,2,28,17) and b==datetime(2024,3,1,17)

@pytest.mark.parametrize('a,b',[('2026-11-01','2026-10-31'),('bad','2026-10-31'),('2026-10-31','2026-02-30'),('0001-01-01',None)])
def test_invalid_ranges(a,b):
    with pytest.raises(Fault):date_range(a,b)

def test_optional_bounds():
    assert date_range()==(None,None)
    assert date_range('2026-10-31',None)[1] is None
    assert date_range(None,'2026-10-31')[0] is None
