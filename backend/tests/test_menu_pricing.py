from decimal import Decimal
import pytest
from app.pricing import menu_prices
from app.db import Fault

GROUPS = [{'id': code, 'code': code, 'active': True} for code in ('WORKER', 'STUDENT', 'VIP', 'CUSTOM')]

@pytest.mark.parametrize('cost,expected', [
    ('50000', ['75000', '71250', '67500', '75000']),
    ('100000', ['150000', '142500', '135000', '150000']),
    ('101', ['152', '144', '137', '152']),
    ('1', ['2', '2', '2', '2']),
    ('0', ['0', '0', '0', '0']),
])
def test_menu_group_prices_and_rounding(cost, expected):
    assert [p['unitPrice'] for p in menu_prices(cost, GROUPS)] == expected

@pytest.mark.parametrize('cost', ['-1', '1.2', 'NaN', '999999999'])
def test_menu_prices_reject_invalid_or_overflowing_amount(cost):
    with pytest.raises(Fault): menu_prices(cost, GROUPS)

def test_disabled_group_does_not_receive_price():
    assert menu_prices('50000', [{**GROUPS[0], 'active': False}]) == []

def test_configured_rules_override_markup_and_group_discounts():
    rules = {'markupPercent': 160, 'groupPercent': {
        'WORKER': 100, 'STUDENT': 85, 'VIP': 75,
    }}
    assert [p['unitPrice'] for p in menu_prices('50000', GROUPS, rules)] == [
        '80000', '68000', '60000', '80000',
    ]
