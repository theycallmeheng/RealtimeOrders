"""Default menu pricing, optionally configured in system_settings."""
from decimal import Decimal, ROUND_HALF_UP
from .db import number, one, T, check

DEFAULT_RULES = {'markupPercent': 150, 'groupPercent': {'STUDENT': 95, 'WORKER': 100, 'VIP': 90}}


def validate_rules(rules):
    check(isinstance(rules,dict) and isinstance(rules.get('groupPercent'),dict),'INVALID_PRICE_RULES','Quy tắc giá không hợp lệ',409)
    markup=number(rules.get('markupPercent'),places=0,minimum=Decimal(1),maximum=Decimal(1000))
    factors={}
    for code,value in rules['groupPercent'].items():
        check(isinstance(code,str) and len(code)<=32,'INVALID_PRICE_RULES','Nhóm trong quy tắc giá không hợp lệ',409)
        factors[code]=int(number(value,places=0,minimum=Decimal(0),maximum=Decimal(1000)))
    return {'markupPercent':int(markup),'groupPercent':factors}


async def load_rules(s):
    row=await one(s,'system_settings',T['system_settings'].c.setting_key=='price_rules',required=False)
    return validate_rules(row['value_json'] if row else DEFAULT_RULES)


def menu_prices(cost, groups, rules=None):
    rules=validate_rules(DEFAULT_RULES if rules is None else rules)
    cost=number(cost,places=0)
    base=(cost*Decimal(rules['markupPercent'])/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
    return [{'groupId':g['id'],'unitPrice':format(number(
        (base*Decimal(rules['groupPercent'].get(g['code'],100))/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP),
        places=0),'f')} for g in groups if g['active']]
