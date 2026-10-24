"""Measure bounded database work and fanout CPU on an isolated MySQL copy.

No credentials or SQL parameter values are included in the report. Synthetic
catalog fixtures are closed after each run; event-write measurements roll back.
"""
import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import time

from sqlalchemy import event, select, update
from sqlalchemy.engine import make_url
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import auth, commerce, events
from app.config import settings
from app.db import Session, T, add, engine, now, one, reflect, uid


def percentile(values, p):
    return round(sorted(values)[int((len(values)-1)*p)], 3)


async def fixtures(count):
    async with Session.begin() as session:
        group_rows = (await session.execute(select(T['customer_groups']))).mappings().all()
        groups = [row['id'] for row in group_rows if row['active']]
        category = (await session.execute(select(T['categories'].c.id).limit(1))).scalar_one()
        unit = (await session.execute(select(T['units'].c.id).limit(1))).scalar_one()
        admin = await one(session, 'users', T['users'].c.role == 'ADMIN', T['users'].c.status == 'ACTIVE')
        customer = await one(session, 'users', T['users'].c.role == 'CUSTOMER', T['users'].c.status == 'ACTIVE')
        product_ids, offer_ids = [], []
        for index in range(count):
            sku = f'PERF-CATALOG-{index:03}'
            product = await one(session, 'products', T['products'].c.sku == sku, required=False)
            if product is None:
                product_id, offer_id = uid(), uid()
                await add(session, 'products', id=product_id, category_id=category, unit_id=unit,
                          sku=sku, name=f'PERF catalog {index:03}', description='Synthetic performance fixture',
                          quantity_step=1, active=True, version=1, created_at=now(), updated_at=now())
                await add(session, 'offers', id=offer_id, product_id=product_id, sale_date=now().date(),
                          batch_code='PERF-CATALOG', status='OPEN', available_qty=1000, opens_at=now()-timedelta(days=1),
                          closes_at=now()+timedelta(days=1), version=1, created_at=now(), updated_at=now())
                for group_id in groups:
                    await add(session, 'offer_prices', offer_id=offer_id, group_id=group_id, unit_price=100000, version=1)
            else:
                product_id = product['id']
                offer = await one(session, 'offers', T['offers'].c.product_id == product_id, T['offers'].c.batch_code == 'PERF-CATALOG')
                offer_id = offer['id']
                await session.execute(update(T['products']).where(T['products'].c.id == product_id).values(active=True))
                await session.execute(update(T['offers']).where(T['offers'].c.id == offer_id).values(status='OPEN'))
            product_ids.append(product_id)
            offer_ids.append(offer_id)
        raw = secrets.token_urlsafe(48)
        session_id = uid()
        await add(session, 'sessions', id=session_id, user_id=admin['id'], token_hash=auth.hashed(raw),
                  security_version=admin['security_version'], created_at=now(), last_activity_at=now(),
                  absolute_expires_at=now()+timedelta(hours=1))
    return admin, customer, raw, session_id, product_ids, offer_ids


async def database_measurements(admin, customer, raw, repeats):
    counts = []

    def count_sql(connection, cursor, statement, parameters, context, executemany):
        counts.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(engine.sync_engine, 'before_cursor_execute', count_sql)
    results = {}
    try:
        for label in ('authenticate', 'customer_catalog', 'admin_catalog', 'flush_100_events'):
            latencies, queries = [], []
            for index in range(repeats + 2):
                async with Session() as session:
                    await session.begin()
                    counts.clear()
                    started = time.perf_counter()
                    if label == 'authenticate':
                        result = await auth.authenticate(session, raw)
                        assert result['id'] == admin['id']
                    elif label.endswith('_catalog'):
                        result = await commerce.catalog(session, admin if label.startswith('admin') else customer,
                                                        admin=label.startswith('admin'))
                        assert any(offer['batch_code'] == 'PERF-CATALOG' for offer in result)
                    else:
                        prefix = 'perf:' + uid()
                        for n in range(100):
                            events.emit(session, prefix + ':' + str(n % 3), 'PERF_PROBE', {'index': n, 'text': 'Tiếng Việt'})
                        await events.flush_events(session)
                    elapsed = (time.perf_counter()-started)*1000
                    query_count = len(counts)
                    await session.rollback()
                    if index >= 2:
                        latencies.append(elapsed)
                        queries.append(query_count)
            results[label] = {'p50Ms': percentile(latencies, .5), 'p95Ms': percentile(latencies, .95),
                              'minSqlStatements': min(queries), 'maxSqlStatements': max(queries),
                              'elapsedMs': latencies, 'sqlStatements': queries}
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', count_sql)
    return results


async def fanout_measurements(repeats):
    results = {}
    for size in (128, 8192):
        timings = []
        for attempt in range(repeats + 2):
            hub = events.Hub()
            subscribers = [events.Subscriber(['catalog:probe'], 'synthetic-' + str(n)) for n in range(2000)]
            for subscriber in subscribers:
                if hasattr(hub, 'register'):
                    hub.register(subscriber)
                else:
                    hub.clients.add(subscriber)
            item = {'topic': 'catalog:probe', 'seq': 1, 'event_id': uid(), 'event_type': 'PERF_PROBE',
                    'entity_id': None, 'entity_version': None, 'payload': {'text': 'x' * size}}
            started = time.perf_counter()
            hub.publish(item)
            for subscriber in subscribers:
                if hasattr(subscriber, 'get_frame'):
                    encoded = (await subscriber.get_frame()).text
                else:
                    encoded = json.dumps(await subscriber.get(), ensure_ascii=False, separators=(',', ':'))
                assert encoded
            if attempt >= 2:
                timings.append((time.perf_counter()-started)*1000)
        results[str(size)] = {'subscribers': 2000, 'payloadTextBytes': size,
                              'p50Ms': percentile(timings, .5), 'p95Ms': percentile(timings, .95), 'elapsedMs': timings}
    return results


async def connectivity_measurements():
    async with Session.begin() as session:
        user=await one(session,'users',T['users'].c.role=='CUSTOMER',T['users'].c.status=='ACTIVE')
        raw=secrets.token_urlsafe(48);session_id=uid()
        await add(session,'sessions',id=session_id,user_id=user['id'],token_hash=auth.hashed(raw),
                  security_version=user['security_version'],created_at=now(),last_activity_at=now(),
                  absolute_expires_at=now()+timedelta(hours=1))
    observations=[]
    try:
        for host in ('localhost','127.0.0.1'):
            for _ in range(4):
                started=time.perf_counter()
                async with websockets.connect(f'wss://{host}:3443/ws',origin=settings.app_origin,
                    ssl=ssl._create_unverified_context(),additional_headers={'Cookie':'ro_session='+raw},open_timeout=10) as ws:
                    opened=time.perf_counter()
                    await ws.send(json.dumps({'v':1,'type':'HELLO','hasModel':False}))
                    while True:
                        message=json.loads(await ws.recv())
                        if message['type']=='SYNC_END':break
                    observations.append({'host':host,'connectMs':round((opened-started)*1000,2),
                                         'syncMs':round((time.perf_counter()-opened)*1000,2)})
    finally:
        async with Session.begin() as session:
            await session.execute(update(T['sessions']).where(T['sessions'].c.id==session_id).values(revoked_at=now()))
    return {'observations':observations,'proxySha256':hashlib.sha256((ROOT/'scripts/proxy.mjs').read_bytes()).hexdigest(),
            'note':'Fresh TLS/WebSocket sessions; same backend, client and origin for both hostnames.'}


async def main(args):
    database = make_url(settings.database_url).database
    if not settings.demo_mode or not database.startswith('realtimeorders_audit_'):
        raise RuntimeError('Use isolated_validation.py to run this probe against an audit database')
    await reflect()
    if args.connectivity_only:
        result=await connectivity_measurements()
        await engine.dispose()
        folder=Path(os.environ.get('AUDIT_EVIDENCE_DIR',ROOT/'evidence'))/'performance'
        folder.mkdir(parents=True,exist_ok=True)
        (folder/('connectivity-'+args.label+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result),flush=True)
        return
    admin, customer, raw, session_id, products, offers = await fixtures(args.offers)
    try:
        database_results = await database_measurements(admin, customer, raw, args.repeats)
        fanout_results = await fanout_measurements(args.repeats)
    finally:
        async with Session.begin() as session:
            await session.execute(update(T['offers']).where(T['offers'].c.id.in_(offers)).values(status='CLOSED'))
            await session.execute(update(T['products']).where(T['products'].c.id.in_(products)).values(active=False))
            await session.execute(update(T['sessions']).where(T['sessions'].c.id == session_id).values(revoked_at=now()))
        await engine.dispose()
    source = {name: hashlib.sha256((ROOT / 'backend/app' / name).read_bytes()).hexdigest()
              for name in ('auth.py', 'commerce.py', 'events.py', 'realtime.py')}
    result = {'label': args.label, 'database': database, 'syntheticOffers': args.offers, 'warmups': 2,
              'repeats': args.repeats, 'databaseMeasurements': database_results, 'fanoutCpuOnly': fanout_results,
              'sourceSha256': source,
              'limitations': ['Fanout CPU excludes WebSocket, TCP/TLS and client parsing.',
                              'SQL statements are counted with SQLAlchemy hooks in this probe process.',
                              'Same-machine MySQL/InnoDB; event-write trials are rolled back.']}
    folder = Path(os.environ.get('AUDIT_EVIDENCE_DIR', ROOT / 'evidence')) / 'performance'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (args.label + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'label': args.label, 'database': database_results, 'fanoutCpuOnly': fanout_results}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True, choices=['baseline', 'optimized'])
    parser.add_argument('--offers', type=int, default=50)
    parser.add_argument('--repeats', type=int, default=10)
    parser.add_argument('--connectivity-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.offers <= 100 or not 3 <= args.repeats <= 100:
        parser.error('offers must be 1..100 and repeats must be 3..100')
    asyncio.run(main(args))
