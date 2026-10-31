"""Fill sample default prices; no historical menu or order prices are updated.
Run with the project venv: python scripts/sample_product_prices.py [--apply].
"""
import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.db import Session, T, reflect, engine, public, now, one, change
from app.commerce import audit, catalog_event
from app.events import flush_events
from app.pricing import menu_prices

# Fabricated coursework prices per configured selling unit, not store quotations.
SKU_COSTS = [38000,30000,18000,21000,4000,3500,28000,27000,12000,14000,
             18000,45000,38000,30000,9000,17000,8000,24000,10000,13000,
             18000,4000,42000,50000,20000,45000,65000,38000,18000,12000,
             15000,10000,22000,18000,20000,14000,35000,18000,12000,24000,
             20000,22000,26000,16000,7000,45000,24000]
COSTS = {f'SKU-{i:06d}': cost for i, cost in enumerate(SKU_COSTS, 1)}
COSTS.update({f'DEMO-{i:03d}': cost for i, cost in enumerate(
    [20000,25000,85000,18000,18000,180000,80000,160000], 1)})
COSTS['0010'] = 220000

async def run(apply):
    await reflect()
    try:
        async with Session.begin() as s:
            query = select(T['products']).where(T['products'].c.deleted_at.is_(None)).order_by(T['products'].c.id)
            if apply: query = query.with_for_update()
            products = [dict(r) for r in (await s.execute(query)).mappings()]
            plan = []
            for p in products:
                cost = COSTS.get(p['sku'], int(p['default_cost_price']) if p['default_cost_price'] is not None else 20000)
                sale = int(menu_prices(cost, [{'id': 'standard', 'code': 'WORKER', 'active': True}])[0]['unitPrice'])
                plan.append({'id': p['id'], 'sku': p['sku'], 'name': p['name'], 'cost': cost, 'sale': sale})
            print(json.dumps(public(plan), ensure_ascii=True, indent=2))
            if not apply:
                print('Preview only. Pass --apply to save sample prices.')
                return
            directory = ROOT / 'runtime' / 'backups'
            directory.mkdir(parents=True, exist_ok=True)
            stamp = now().strftime('%Y%m%dT%H%M%S%fZ')
            backup = directory / f'product-default-prices-{stamp}.json'
            backup.write_text(json.dumps(public(products), ensure_ascii=False, indent=2), encoding='utf-8')
            user = await one(s, 'users', T['users'].c.role == 'ADMIN')
            changed = 0
            for old, item in zip(products, plan):
                if old['default_cost_price'] == item['cost'] and old['default_sale_price'] == item['sale']: continue
                values = {'default_cost_price': Decimal(item['cost']), 'default_sale_price': Decimal(item['sale'])}
                await change(s, 'products', old['id'], **values, version=old['version'] + 1, updated_at=now())
                await audit(s, user, 'product.sample_prices', 'product', old['id'],
                            {k: old[k] for k in values}, values)
                changed += 1
            if changed:
                await catalog_event(s, [])
                await flush_events(s)
            print(f'Updated {changed} of {len(products)} products. Backup: runtime/backups/{backup.name}')
    finally:
        await engine.dispose()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
