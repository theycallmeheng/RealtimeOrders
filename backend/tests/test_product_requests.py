"""Private requests over real TCP/MySQL on the isolated validation database."""
import asyncio
from datetime import timedelta
from decimal import Decimal
import httpx
import pytest_asyncio
from sqlalchemy import select, update, func
from app import product_requests as pr
from app.db import T, Session, add, change, now, uid, one
from app.events import flush_events
from app.menus import bounds, today
from conftest import Client, ORIGIN, DATA
from test_shop_workflow import roles


@pytest_asyncio.fixture(autouse=True)
async def restore_shared_menu(clients):
    async with Session.begin() as s:
        menu = await one(s, 'daily_menus', T['daily_menus'].c.id == DATA['testMenuId'])
    yield
    async with Session.begin() as s:
        await change(s, 'daily_menus', menu['id'], **{k: menu[k] for k in ('status', 'opens_at', 'closes_at')})


@pytest_asyncio.fixture
async def requester(clients):
    template = clients[1]
    async with Session.begin() as s:
        original = await one(s, 'users', T['users'].c.id == template.user['id'])
        phone = '+849' + str(int(uid().replace('-', '')[:8], 16) % 100000000).zfill(8)
        await add(s, 'users', id=uid(), phone_e164=phone, password_hash=original['password_hash'],
            display_name='Request test customer', role='CUSTOMER', status='ACTIVE', group_id=original['group_id'],
            phone_verified_at=now(), security_version=1, version=1, created_at=now(), updated_at=now())
    async with httpx.AsyncClient(base_url=ORIGIN, verify=False, timeout=30) as http:
        response = await http.post('/api/v1/auth/login', headers={'Origin': ORIGIN},
            json={'identifier': phone, 'password': DATA['accounts'][1]['password']})
        assert response.status_code == 200, response.text
        yield Client(http, response.json())


def body(**kwargs):
    return {'shopId': '00000000-0000-4000-8000-000000000001', 'name': 'Sữa yến mạch ' + uid()[:8],
        'description': 'Loại không đường, hộp 1 lít', 'quantity': '2.5', 'unit': 'hộp',
        'imageUrl': 'https://example.org/image.png', 'referenceUrl': 'https://example.org/item', 'desiredPrice': '40000', **kwargs}


async def command(actor, request, status, **kwargs):
    r = await actor.request('PATCH', '/admin/product-requests/' + request['id'],
        {'expectedVersion': request['version'], 'status': status, **kwargs})
    assert r.status_code == 200, r.text
    return r.json()


async def test_creation_retry_private_topics_and_duplicate(requester, clients, roles):
    customer = requester; admin = clients[0]; seller, courier, _ = roles
    payload = body(); key = uid()
    replies = await asyncio.gather(*(customer.request('POST', '/product-requests', payload, key) for _ in range(4)))
    assert all(r.status_code == 200 for r in replies), [r.text for r in replies]
    assert len({r.json()['id'] for r in replies}) == 1
    row = replies[0].json()
    assert row['status'] == 'PENDING' and Decimal(row['quantity']) == Decimal('2.5')
    assert 'name_key' not in row and 'password_hash' not in str(row)
    duplicate = await customer.request('POST', '/product-requests', {**payload, 'name': '  ' + payload['name'].upper() + '  '})
    assert duplicate.status_code == 409 and duplicate.json()['error']['code'] == 'REQUEST_DUPLICATE'
    assert (await clients[2].request('GET', '/product-requests/' + row['id'])).status_code == 403
    assert row['id'] in [r['id'] for r in await seller.get('/shop/product-requests')]
    assert row['id'] in [r['id'] for r in await admin.get('/admin/product-requests')]
    assert (await courier.request('GET', '/product-requests')).status_code == 403
    assert (await seller.request('POST', '/product-requests', payload)).status_code == 403
    async with Session.begin() as s:
        e = T['stream_events']
        topics = (await s.execute(select(e.c.topic).where(e.c.event_type == 'PRODUCT_REQUEST_CHANGED',
            func.json_unquote(func.json_extract(e.c.payload, '$.id')) == row['id']))).scalars().all()
        assert set(topics) == {'user:' + customer.user['id'], 'shop:' + row['shop_id'] + ':ops', 'admin:ops'}
        assert not any(topic.startswith('catalog:') for topic in topics)


async def test_daily_quota_concurrent_cancel_and_vietnam_boundary(requester, clients):
    payloads = [body() for _ in range(7)]
    replies = await asyncio.gather(*(requester.request('POST', '/product-requests', data) for data in payloads))
    assert sum(r.status_code == 200 for r in replies) == 5
    assert sum(r.status_code == 429 for r in replies) == 2
    created = [r.json() for r in replies if r.status_code == 200]
    await requester.post('/product-requests/' + created[0]['id'] + '/cancel', {'expectedVersion': created[0]['version']})
    assert (await requester.request('POST', '/product-requests', body())).status_code == 429
    # Move only this fixture's requests before VN midnight; quota is based on creation, not status.
    async with Session.begin() as s:
        await s.execute(update(T['product_requests']).where(T['product_requests'].c.customer_id == requester.user['id'])
            .values(created_at=bounds(today())[0] - timedelta(microseconds=1)))
    assert (await requester.request('POST', '/product-requests', body())).status_code == 200


async def test_edit_cancel_version_and_rejection(requester, clients):
    admin = clients[0]; payload = body(); row = await requester.post('/product-requests', payload)
    edited = await requester.request('PATCH', '/product-requests/' + row['id'], {**payload, 'name': 'Tên mới', 'expectedVersion': row['version']})
    assert edited.status_code == 200, edited.text
    stale = await requester.request('PATCH', '/product-requests/' + row['id'], {**payload, 'expectedVersion': row['version']})
    assert stale.status_code == 409
    row = await command(admin, edited.json(), 'REVIEWING')
    assert (await requester.request('PATCH', '/product-requests/' + row['id'], {**payload, 'expectedVersion': row['version']})).status_code == 409
    rejected = await admin.request('PATCH', '/admin/product-requests/' + row['id'], {'expectedVersion': row['version'], 'status': 'REJECTED'})
    assert rejected.status_code == 400
    row = await command(admin, row, 'REJECTED', note='Shop không nhập được loại này')
    assert (await requester.request('POST', '/product-requests/' + row['id'] + '/cancel', {'expectedVersion': row['version']})).status_code == 409
    other = await requester.post('/product-requests', body())
    other = await command(admin, other, 'REVIEWING')
    cancelled = await requester.post('/product-requests/' + other['id'] + '/cancel', {'expectedVersion': other['version']})
    assert cancelled['status'] == 'CANCELLED'
    assert (await admin.request('PATCH', '/admin/product-requests/' + other['id'], {'expectedVersion': cancelled['version'], 'status': 'WAITING'})).status_code == 409
    notes = await requester.get('/notifications')
    assert any(n['kind'] == 'PRODUCT_REQUEST_STATUS' and 'Shop không nhập' in n['payload']['message'] for n in notes)


async def test_link_future_open_restocks_and_single_notification(requester, clients, sale):
    admin = clients[0]
    async with Session.begin() as s:
        await change(s, 'daily_menus', sale['menu_id'], status='OPEN', opens_at=now() - timedelta(hours=1), closes_at=now() + timedelta(hours=2))
        await change(s, 'offers', sale['id'], available_qty=0)
    row = await requester.post('/product-requests', body())
    row = await command(admin, row, 'REVIEWING')
    row = await command(admin, row, 'WAITING', productId=sale['product_id'])
    assert row['status'] == 'WAITING'  # An open, sold-out offer is not enough.
    async with Session.begin() as s:
        await change(s, 'offers', sale['id'], available_qty=10)
        await change(s, 'daily_menus', sale['menu_id'], opens_at=now() + timedelta(hours=1))
        await pr.opened_batch(s); await flush_events(s)
    assert (await requester.get('/product-requests/' + row['id']))['status'] == 'WAITING'
    async with Session.begin() as s:
        await change(s, 'daily_menus', sale['menu_id'], opens_at=now() - timedelta(hours=1))
        await pr.opened_batch(s); await pr.opened_batch(s); await flush_events(s)
    result = await requester.get('/product-requests/' + row['id'])
    assert result['status'] == 'OPENED' and result['offer_id'] == sale['id']
    notes = await requester.get('/notifications')
    assert len([n for n in notes if n['kind'] == 'PRODUCT_REQUEST_OPENED' and n['payload']['requestId'] == row['id']]) == 1
    assert (await requester.request('POST', '/product-requests/' + row['id'] + '/cancel', {'expectedVersion': result['version']})).status_code == 409


async def test_cross_shop_and_group_restrictions(requester, clients, sale, roles):
    admin = clients[0]; seller = roles[0]
    row = await requester.post('/product-requests', body())
    row = await command(admin, row, 'REVIEWING')
    async with Session.begin() as s:
        shop_id = uid()
        await add(s, 'shops', id=shop_id, name='Other request shop', profile_json={}, active=True,
            version=1, warehouse_version=0, created_at=now(), updated_at=now())
    template = (await admin.get('/admin/products'))[0]
    product = await admin.post('/admin/products', {'shopId': shop_id, 'name': 'Other request product',
        'categoryId': template['category_id'], 'unitId': template['unit_id'], 'quantityStep': '1'})
    r = await admin.request('PATCH', '/admin/product-requests/' + row['id'],
        {'expectedVersion': row['version'], 'status': 'WAITING', 'productId': product['id']})
    assert r.status_code == 404
    # Another shop's request must not reach this seller's list, detail, or mutation.
    other = await requester.post('/product-requests', body(shopId=shop_id))
    assert other['id'] not in [r['id'] for r in await seller.get('/shop/product-requests')]
    assert (await seller.request('GET', '/shop/product-requests/' + other['id'])).status_code == 403
    assert (await seller.request('PATCH', '/shop/product-requests/' + other['id'], {'expectedVersion': other['version'], 'status': 'REVIEWING'})).status_code == 403
    async with Session.begin() as s:
        others = [g['id'] for g in (await s.execute(select(T['customer_groups']).where(T['customer_groups'].c.id != requester.user['group_id']))).mappings()]
        await change(s, 'products', sale['product_id'], allowed_group_ids=others)
    r = await admin.request('PATCH', '/admin/product-requests/' + row['id'],
        {'expectedVersion': row['version'], 'status': 'WAITING', 'productId': sale['product_id']})
    assert r.status_code == 409 and r.json()['error']['code'] == 'GROUP_RESTRICTED'


async def test_invalid_input_and_waiting_cancellation(requester, clients, sale):
    async with Session.begin() as s:
        await change(s, 'daily_menus', sale['menu_id'], status='DRAFT')
    for changes in ({'quantity': '0'}, {'quantity': 'NaN'}, {'desiredPrice': '-1'}, {'imageUrl': 'javascript:alert(1)'}, {'name': ''}, {'description': ''}):
        assert (await requester.request('POST', '/product-requests', body(**changes))).status_code == 400
    row = await requester.post('/product-requests', body())
    row = await command(clients[0], row, 'REVIEWING')
    row = await command(clients[0], row, 'WAITING', productId=sale['product_id'])
    assert row['status'] == 'WAITING'  # The shared draft menu is not open.
    row = await requester.post('/product-requests/' + row['id'] + '/cancel', {'expectedVersion': row['version']})
    async with Session.begin() as s:
        await change(s, 'daily_menus', sale['menu_id'], status='OPEN', opens_at=now() - timedelta(hours=1), closes_at=now() + timedelta(hours=1))
        await pr.opened_batch(s); await flush_events(s)
    assert (await requester.get('/product-requests/' + row['id']))['status'] == 'CANCELLED'
