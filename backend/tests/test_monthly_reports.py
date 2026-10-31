from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock,patch
import pytest
from app import analytics
from app.db import Fault

@pytest.mark.parametrize('month,length,last', [('2024-02',29,'2024-02-29'),('2025-02',28,'2025-02-28'),('2026-04',30,'2026-04-30'),('2026-12',31,'2026-12-31')])
def test_calendar_month(month,length,last):
    days=analytics.month_days(month)
    assert len(days)==length and days[-1].isoformat()==last

@pytest.mark.parametrize('value', ['', '2026-00','2026-13','2026-2','2026-02-01','0000-01',None])
def test_invalid_month(value):
    with pytest.raises(Fault): analytics.month_days(value)

def record(revenue,cost,missing=0):
    return dict(orders=1,merchandise=Decimal(revenue),shipping=Decimal(3000),cost=Decimal(cost) if cost is not None else None,missingCostLines=missing)

def test_month_loss_decimal_cost_and_separate_shipping():
    result=analytics.month_total('2026-10',[record(10000,12000),record(5000,6000)])
    assert result['merchandise']==15000 and result['cost']==18000 and result['grossProfit']==-3000
    assert result['shipping']==6000 and result['orders']==2

def test_missing_cost_never_becomes_zero():
    result=analytics.month_total('2026-10',[record(10000,12000),record(5000,None,1)])
    assert result['merchandise']==15000 and result['cost'] is None and result['grossProfit'] is None
    assert result['missingCostLines']==1

def test_zero_comparison_has_no_percentage_and_losses_use_absolute_denominator():
    a={'orders':2,'merchandise':Decimal(5000),'grossProfit':Decimal(-500)}
    b={'orders':0,'merchandise':Decimal(0),'grossProfit':Decimal(-1000)}
    result=analytics.compare_records(a,b)
    assert result['merchandise']=={'amount':Decimal(5000),'percent':None}
    assert result['grossProfit']['percent']==50

async def test_default_previous_month_crosses_year_and_same_month_is_zero():
    async def fake(s,dates):
        return {str(d):dict(day=str(d),orders=0,merchandise=Decimal(0),shipping=Decimal(0),cost=Decimal(0),grossProfit=Decimal(0),missingCostLines=0) for d in set(dates)}
    with patch.object(analytics,'daily_records',AsyncMock(side_effect=fake)):
        result=await analytics.monthly_report(None,'2027-01')
        assert result['comparison']['month']=='2026-12' and len(result['daily'])==31
        result=await analytics.monthly_report(None,'2024-02','2024-02')
        assert len(result['daily'])==29 and result['changes']['orders']['amount']==0


async def test_daily_view_returns_exactly_seven_days_even_with_distant_comparison():
    async def fake(s,dates):
        return {str(d):dict(day=str(d),orders=0,merchandise=Decimal(0),shipping=Decimal(0),cost=Decimal(0),grossProfit=Decimal(0),missingCostLines=0) for d in set(dates)}
    with patch.object(analytics,'daily_records',AsyncMock(side_effect=fake)):
        result=await analytics.report(None,'2026-10-31','2026-09-01')
        assert [r['day'] for r in result['daily']]==['2026-10-25','2026-10-26','2026-10-27','2026-10-28','2026-10-29','2026-10-30','2026-10-31']
        assert result['comparison']['day']=='2026-09-01'
