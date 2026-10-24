"""Regression probes found during the 24 October isolated audit."""
import asyncio
from contextlib import suppress
import json
import ssl
import os
from pathlib import Path
import secrets
import time
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
import websockets

from app import events
from app.auth import csrf, hashed
from app.db import Session, T, add, now, one, uid
from conftest import Client, ORIGIN, order_body
from test_integration import sync_messages


@pytest.mark.parametrize('line', [None, 1, 'invalid', []])
async def test_order_rejects_non_object_lines(clients, sale, line):
    customer = clients[1]
    body = await order_body(customer, sale)
    body['items'] = [line]
    response = await customer.request('POST', '/orders', body)
    assert response.status_code == 400, response.text
    async with Session.begin() as session:
        assert await one(session, 'orders', T['orders'].c.client_order_id == body['clientOrderId'], required=False) is None


@pytest.mark.parametrize('prices', [None, {}, 1, 'invalid', [None], [[]]])
async def test_offer_rejects_invalid_price_collections(clients, sale, prices):
    response = await clients[0].request('PATCH', '/admin/offers/' + sale['id'], {'expectedVersion': '1', 'prices': prices})
    assert response.status_code == 400, response.text
    async with Session.begin() as session:
        assert (await one(session, 'offers', T['offers'].c.id == sale['id']))['version'] == 1


@pytest.mark.parametrize('assets', [[{}], [[]]])
async def test_product_rejects_nested_asset_ids(clients, assets):
    product = (await clients[0].get('/admin/products'))[0]
    response = await clients[0].request('PATCH', '/admin/products/' + product['id'], {'expectedVersion': str(product['version']), 'assetIds': assets})
    assert response.status_code == 400, response.text
    async with Session.begin() as session:
        assert (await one(session, 'products', T['products'].c.id == product['id']))['version'] == int(product['version'])


@pytest.mark.parametrize('assets', [[{}], [[]]])
async def test_chat_rejects_nested_asset_ids(clients, assets):
    customer = clients[1]
    conversation = await customer.get('/conversations/me')
    response = await customer.request('POST', '/conversations/' + conversation['id'] + '/messages',
                                      {'clientMessageId': uid(), 'text': 'Invalid attachment probe', 'assetIds': assets})
    assert response.status_code == 400, response.text


@pytest.mark.parametrize('value', ['false', 1, None, [], {}])
async def test_processing_lock_requires_boolean(clients, sale, value):
    response = await clients[0].request('PATCH', '/admin/offers/' + sale['id'], {'expectedVersion': '1', 'processingLocked': value})
    assert response.status_code == 400, response.text
    async with Session.begin() as session:
        offer = await one(session, 'offers', T['offers'].c.id == sale['id'])
        assert offer['version'] == 1 and offer['processing_locked_at'] is None


@pytest.mark.parametrize('value', ['false', 1, None])
async def test_default_address_requires_boolean(clients, value):
    customer = clients[1]
    address = (await customer.get('/me/addresses'))[0]
    response = await customer.request('PATCH', '/me/addresses/' + address['id'], {'expectedVersion': str(address['version']), 'makeDefault': value})
    assert response.status_code == 400, response.text
    assert response.json()['error']['code'] == 'INVALID_BOOLEAN'


@pytest.mark.parametrize('value', ['true', None])
async def test_cancel_decision_requires_boolean(clients, sale, value):
    admin, customer = clients[:2]
    order = await customer.post('/orders', await order_body(customer, sale))
    order = await admin.post('/admin/orders/' + order['id'] + '/approve', {'expectedVersion': '1'})
    order = await customer.post('/orders/' + order['id'] + '/cancellation-requests', {'expectedVersion': str(order['version']), 'reason': 'Audit cancellation decision'})
    response = await admin.request('POST', '/admin/orders/' + order['id'] + '/decide-cancel',
                                   {'expectedVersion': str(order['version']), 'accept': value})
    assert response.status_code == 400, response.text
    current = await customer.get('/orders/' + order['id'])
    assert current['status'] == 'APPROVED'
    assert any(request['state'] == 'OPEN' for request in current['cancellation_requests'])


async def test_excessive_json_nesting_returns_client_error(clients):
    customer = clients[1]
    response = await customer.http.post('/api/v1/product-requests',
        content=b'{"note":' + b'[' * 1200 + b'0' + b']' * 1200 + b'}',
        headers={'Origin': ORIGIN, 'X-CSRF-Token': customer.session['csrfToken'], 'Content-Type': 'application/json'})
    assert response.status_code == 400, response.text


@pytest.mark.parametrize('synchronized', [False, True])
async def test_binary_websocket_frames_are_rejected_cleanly(clients, synchronized):
    customer = clients[1]
    cookie = '; '.join(key + '=' + value for key, value in customer.http.cookies.items())
    async with websockets.connect(ORIGIN.replace('https:', 'wss:') + '/ws', origin=ORIGIN,
                                  additional_headers={'Cookie': cookie}, ssl=ssl._create_unverified_context()) as socket:
        if synchronized:
            await socket.send(json.dumps({'v': 1, 'type': 'HELLO', 'hasModel': False}))
            await sync_messages(socket)
        await socket.send(b'{}')
        while True:
            message = json.loads(await asyncio.wait_for(socket.recv(), 3))
            if message['type'] == 'PING':
                await socket.send(json.dumps({'v': 1, 'type': 'PONG'}))
            if message['type'] == 'ERROR':
                break
        assert message['type'] == 'ERROR' and message['code'] == 'INVALID_MESSAGE'
        await asyncio.wait_for(socket.wait_closed(), 3)
        assert socket.close_code in (1003, 1008)


async def test_outbox_recovers_if_first_database_read_fails(monkeypatch):
    real_session = events.Session
    recovered = asyncio.Event()
    attempts = 0

    class FailFirstRead:
        def begin(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError('audit transient database outage', None, RuntimeError('temporary test failure'))
            recovered.set()
            return real_session.begin()

    monkeypatch.setattr(events, 'Session', FailFirstRead())
    task = asyncio.create_task(events.outbox_worker())
    try:
        await asyncio.wait_for(recovered.wait(), 1)
        assert not task.done(), 'Outbox worker stopped after a transient database failure'
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def test_twenty_customers_compete_for_ten_units(clients, sale):
    """Distinct users and admin sessions contend on one real InnoDB stock row."""
    customers, administrators, identities, session_ids = [], [], [], []
    template = await order_body(clients[1], sale)
    async with Session.begin() as session:
        base = await one(session, 'users', T['users'].c.id == clients[1].user['id'])
        admin = await one(session, 'users', T['users'].c.id == clients[0].user['id'])
        address = await one(session, 'addresses', T['addresses'].c.id == template['addressId'])
        for index in range(20):
            user_id, address_id = uid(), uid()
            identities.append(user_id)
            user = await add(session, 'users', id=user_id, phone_e164='+99' + str(secrets.randbelow(10**10)).zfill(10),
                display_name='AUDIT-CONTENTION-' + str(index), password_hash=base['password_hash'], role='CUSTOMER', status='ACTIVE',
                group_id=base['group_id'], phone_verified_at=now(), security_version=1, version=1, created_at=now(), updated_at=now())
            await add(session, 'addresses', id=address_id, user_id=user_id, zone_id=address['zone_id'],
                recipient_name='Audit customer', phone_e164=user['phone_e164'], address_line='Synthetic contention test address',
                version=1, created_at=now(), updated_at=now())
            for collection, account in ((customers, user), (administrators, admin)):
                raw = secrets.token_urlsafe(48)
                session_id = uid()
                session_ids.append(session_id)
                await add(session, 'sessions', id=session_id, user_id=account['id'], token_hash=hashed(raw), security_version=account['security_version'],
                    created_at=now(), last_activity_at=now(), absolute_expires_at=now()+timedelta(hours=1))
                http = httpx.AsyncClient(base_url=ORIGIN, verify=False, timeout=30, cookies={'ro_session': raw})
                collection.append(Client(http, {'user': account, 'csrfToken': csrf(raw)}))
            customers[-1].address_id = address_id
    try:
        orders = await asyncio.gather(*(customer.post('/orders', {**template, 'clientOrderId': uid(), 'addressId': customer.address_id}) for customer in customers))
        latencies = []

        async def approve(index, order):
            start = time.perf_counter()
            response = await administrators[index].request('POST', '/admin/orders/' + order['id'] + '/approve', {'expectedVersion': '1'})
            latencies.append((time.perf_counter()-start)*1000)
            return response

        responses = await asyncio.gather(*(approve(index, order) for index, order in enumerate(orders)))
        approved = sum(response.status_code == 200 for response in responses)
        conflicts = sum(response.status_code == 409 for response in responses)
        assert approved == conflicts == 10
        assert all(response.status_code in (200, 409) for response in responses)
        async with Session.begin() as session:
            stock = await one(session, 'offers', T['offers'].c.id == sale['id'])
            ledger = (await session.execute(select(func.count()).select_from(T['inventory_movements']).where(
                T['inventory_movements'].c.offer_id == sale['id'], T['inventory_movements'].c.kind == 'APPROVE'))).scalar_one()
            assert stock['available_qty'] == 0 and ledger == 10
        evidence = os.environ.get('AUDIT_EVIDENCE_DIR')
        if evidence:
            Path(evidence, 'stock-contention.json').write_text(json.dumps({
                'distinctCustomers': 20, 'distinctAdminSessions': 20, 'initialStock': 10, 'pendingOrders': len(orders),
                'approved': approved, 'expectedStockConflicts': conflicts, 'technicalErrors': 0, 'remainingStock': 0,
                'approvalLedgerEntries': ledger, 'approvalP50Ms': round(sorted(latencies)[9], 2),
                'approvalP95Ms': round(sorted(latencies)[18], 2), 'latenciesMs': latencies,
                'topology': 'Same Windows machine, HTTPS and real MySQL/InnoDB.'}, indent=2) + '\n', encoding='utf-8')
    finally:
        await asyncio.gather(*(client.http.aclose() for client in customers + administrators))
        async with Session.begin() as session:
            await session.execute(update(T['sessions']).where(T['sessions'].c.id.in_(session_ids)).values(revoked_at=now()))
            await session.execute(update(T['users']).where(T['users'].c.id.in_(identities)).values(status='DELETED'))


async def test_product_request_retry_does_not_create_duplicates(clients):
    customer = clients[1]
    body = {'itemName': 'Audit lost acknowledgment ' + uid(), 'unitLabel': 'kg', 'quantity': '1'}
    key = uid()
    responses = await asyncio.gather(*(customer.request('POST', '/product-requests', body, key) for _ in range(5)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()['id'] for response in responses}) == 1
    conflict = await customer.request('POST', '/product-requests', {**body, 'quantity': '2'}, key)
    assert conflict.status_code == 409


async def test_address_retry_does_not_fill_address_slots(clients):
    customer = clients[1]
    previous = await customer.get('/me/addresses')
    previous_ids = [address['id'] for address in previous]
    assert len(previous) < 3
    template = previous[0]
    body = {'zoneId': template['zone_id'], 'recipientName': 'Audit retry', 'phone': customer.user['phone_e164'],
            'addressLine': 'Synthetic audit retry ' + uid()}
    try:
        key = uid()
        responses = await asyncio.gather(*(customer.request('POST', '/me/addresses', body, key) for _ in range(5)))
        assert all(response.status_code == 200 for response in responses)
        assert len({response.json()['id'] for response in responses}) == 1
        assert len(await customer.get('/me/addresses')) == len(previous) + 1
    finally:
        async with Session.begin() as session:
            await session.execute(update(T['addresses']).where(T['addresses'].c.user_id == customer.user['id'],
                T['addresses'].c.id.not_in(previous_ids)).values(deleted_at=now()))
