"""Correctness contracts preserved by batching and shared event encoding."""
import asyncio
import json
from decimal import Decimal
import socket

import httpx
import pytest
from sqlalchemy import event, func, select, update

from app import auth, commerce
from app.db import Fault, Session, T, engine, now, reflect, uid
from app.events import Hub, Subscriber, emit, event_wire, flush_events
from test_integration import socket as open_socket, sync_messages
from conftest import order_body


def sample_event(topic, number=1):
    return {'topic': topic, 'seq': number, 'event_id': uid(), 'event_type': 'TEST_SHARED_FRAME',
            'entity_id': None, 'entity_version': 2**60, 'payload': {'text': 'Tiếng Việt 🟩', 'amount': '100000'}}


async def test_shared_frame_preserves_payload_and_topic_privacy():
    hub = Hub()
    first = Subscriber(['user:first', 'catalog:shared'], 'first')
    second = Subscriber(['user:second', 'catalog:shared'], 'second')
    admin = Subscriber(['admin:ops'], 'admin')
    for subscriber in (first, second, admin):
        hub.register(subscriber)
    private = sample_event('user:first')
    hub.publish(private)
    assert first.queue.qsize() == 1 and second.queue.empty() and admin.queue.empty()
    assert (await first.get_frame()).message == event_wire(private)
    shared = sample_event('catalog:shared')
    hub.publish(shared)
    first_frame, second_frame = await first.get_frame(), await second.get_frame()
    assert first_frame is second_frame
    assert json.loads(first_frame.text) == event_wire(shared)
    assert first_frame.size == len(first_frame.text.encode('utf-8'))
    assert first.bytes == second.bytes == 0
    for subscriber in (first, second, admin):
        hub.unregister(subscriber)
        hub.unregister(subscriber)
    assert not hub.clients and not hub.by_topic


async def test_slow_subscriber_isolated_from_other_topic():
    hub = Hub()
    slow, healthy = Subscriber(['catalog:slow'], 'slow'), Subscriber(['catalog:healthy'], 'healthy')
    hub.register(slow)
    hub.register(healthy)
    item = sample_event('catalog:slow')
    item['payload']['text'] = 'x' * 8192
    for _ in range(300):
        hub.publish(item)
    assert slow.slow and slow.queue.qsize() <= 128 and slow.bytes <= 512*1024
    assert healthy.queue.empty()
    expected = sample_event('catalog:healthy')
    hub.publish(expected)
    assert (await healthy.get_frame()).message == event_wire(expected)
    assert not healthy.slow


async def test_legacy_subscriber_get_keeps_utf8_byte_accounting():
    subscriber = Subscriber(['user:test'], 'test')
    message = {'v': 1, 'type': 'SESSION_REVOKED', 'message': 'Phiên đã hết hạn 🟩'}
    subscriber.put(message)
    assert subscriber.bytes == len(json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode())
    assert await subscriber.get() == message
    assert subscriber.bytes == 0


async def test_batched_event_writes_rollback_together():
    await reflect()
    topics = ['perf-rollback:' + uid(), 'perf-rollback:' + uid()]
    event_ids = []
    async with Session() as session:
        await session.begin()
        for index in range(20):
            emit(session, topics[index % 2], 'ROLLBACK_PROBE', {'index': index})
        await flush_events(session)
        event_ids = (await session.execute(select(T['stream_events'].c.event_id).where(T['stream_events'].c.topic.in_(topics)))).scalars().all()
        assert len(event_ids) == 20
        await session.rollback()
    async with Session.begin() as session:
        for table, condition in (
            ('stream_events', T['stream_events'].c.topic.in_(topics)),
            ('stream_heads', T['stream_heads'].c.topic.in_(topics)),
            ('outbox', T['outbox'].c.event_id.in_(event_ids)),
        ):
            assert (await session.execute(select(func.count()).select_from(T[table]).where(condition))).scalar_one() == 0


async def test_batched_event_writes_keep_sequence_and_outbox_links():
    await reflect()
    topics = ['perf-sequence:' + uid() for _ in range(3)]
    async with Session.begin() as session:
        for index in range(100):
            emit(session, topics[index % 3], 'BATCH_PROBE', {'index': index, 'amount': Decimal('1.00')}, version=2**60)
        await flush_events(session)
    async with Session.begin() as session:
        entries = (await session.execute(select(T['stream_events']).where(T['stream_events'].c.topic.in_(topics)))).mappings().all()
        assert len(entries) == 100
        for offset, topic in enumerate(topics):
            group = sorted((row for row in entries if row['topic'] == topic), key=lambda row: row['seq'])
            assert [row['seq'] for row in group] == list(range(1, len(group)+1))
            assert [row['payload']['index'] for row in group] == list(range(offset, 100, 3))
            assert all(row['payload']['amount'] == '1.00' and event_wire(row)['entityVersion'] == str(2**60) for row in group)
        links = (await session.execute(select(func.count()).select_from(T['outbox']).where(T['outbox'].c.event_id.in_([row['event_id'] for row in entries])))).scalar_one()
        assert links == 100


async def test_catalog_batches_admin_prices_without_exposing_other_groups(clients, sale):
    admin, student, worker = clients[:3]
    async with Session.begin() as session:
        for user, amount in ((student.user, 123000), (worker.user, 456000)):
            await session.execute(update(T['offer_prices']).where(T['offer_prices'].c.offer_id == sale['id'],
                T['offer_prices'].c.group_id == user['group_id']).values(unit_price=amount))
    queries = []

    def count(connection, cursor, statement, parameters, context, executemany):
        queries.append(1)

    event.listen(engine.sync_engine, 'before_cursor_execute', count)
    try:
        async with Session.begin() as session:
            admin_result = await commerce.catalog(session, admin.user, admin=True)
        assert len(queries) <= 5, 'Catalog database work must not grow one price query per offer'
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', count)
    selected = next(offer for offer in admin_result if offer['id'] == sale['id'])
    assert {price['group_id']: price['unit_price'] for price in selected['prices']} == {
        student.user['group_id']: '123000', worker.user['group_id']: '456000'}
    for client, expected in ((student, '123000'), (worker, '456000')):
        async with Session.begin() as session:
            result = await commerce.catalog(session, client.user, offer_ids=[sale['id']])
        assert result[0]['unit_price'] == expected and 'prices' not in result[0]


async def test_authentication_reads_current_user_and_session_in_one_query(clients):
    client = clients[1]
    queries = []

    def count(connection, cursor, statement, parameters, context, executemany):
        queries.append(1)

    event.listen(engine.sync_engine, 'before_cursor_execute', count)
    try:
        async with Session.begin() as session:
            user = await auth.authenticate(session, client.http.cookies['ro_session'])
            assert user['id'] == client.user['id'] and user['group_id'] == client.user['group_id']
            assert session.info['authenticated_session_id'] != user['id']
        assert len(queries) == 1
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', count)


@pytest.mark.parametrize('host', ['127.0.0.1', '[::1]'])
async def test_loopback_families_keep_https_and_authorization(clients, host):
    if host == '[::1]':
        if not socket.has_ipv6:
            pytest.skip('IPv6 is unavailable on this host')
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
                probe.bind(('::1', 0))
        except OSError:
            pytest.skip('IPv6 loopback is disabled on this host')
    async with httpx.AsyncClient(base_url=f'https://{host}:3443', verify=False, trust_env=False) as client:
        assert (await client.get('/api/health')).status_code == 200
        assert (await client.get('/api/v1/orders')).status_code == 401


async def test_resync_is_not_interleaved_with_live_events(clients):
    client=clients[1]
    ws=await open_socket(client)
    await sync_messages(ws)
    topic='user:'+client.user['id']
    marker=uid()

    async def produce():
        for index in range(20):
            async with Session.begin() as session:
                emit(session,topic,'SYNC_PROBE',{'marker':marker,'index':index})
                await flush_events(session)
            await asyncio.sleep(.003)

    producer=asyncio.create_task(produce())
    try:
        await ws.send(json.dumps({'v':1,'type':'RESYNC_REQUEST','hasModel':False}))
        syncing=False
        while True:
            message=json.loads(await asyncio.wait_for(ws.recv(),15))
            if message['type']=='PING':
                assert not syncing
                await ws.send(json.dumps({'v':1,'type':'PONG'}))
            elif message['type']=='SYNC_BEGIN':
                syncing=True
                assert message['mode']=='SNAPSHOT'
            elif syncing:
                assert message['type'] in ('SNAPSHOT_CHUNK','SYNC_END')
                if message['type']=='SYNC_END':break
        await producer
        async with Session.begin() as session:
            emit(session,topic,'SYNC_FOLLOWUP',{'marker':marker})
            await flush_events(session)
        while True:
            message=json.loads(await asyncio.wait_for(ws.recv(),15))
            if message['type']=='PING':await ws.send(json.dumps({'v':1,'type':'PONG'}))
            if message.get('eventType')=='SYNC_FOLLOWUP':
                assert message['payload']['marker']==marker
                break
    finally:
        producer.cancel()
        await asyncio.gather(producer,return_exceptions=True)
        await ws.close()


async def test_batched_order_details_preserve_content_order_and_privacy(clients,sale):
    client,other=clients[1:3]
    created=[await client.post('/orders',await order_body(client,sale)) for _ in range(3)]
    ids=[created[2]['id'],created[0]['id'],created[1]['id']]
    foreign=await other.post('/orders',await order_body(other,sale))
    async with Session.begin() as session:
        expected=[await commerce.get_order(session,client.user,id) for id in ids]
    queries=[]
    def count(connection,cursor,statement,parameters,context,executemany):queries.append(1)
    event.listen(engine.sync_engine,'before_cursor_execute',count)
    try:
        async with Session.begin() as session:actual=await commerce.get_orders(session,client.user,ids)
        assert len(queries)==4
    finally:event.remove(engine.sync_engine,'before_cursor_execute',count)
    def normalized(orders):
        return [{**order,'items':sorted(order['items'],key=lambda item:item['id']),
                 'cancellation_requests':sorted(order['cancellation_requests'],key=lambda item:item['id'])} for order in orders]
    assert normalized(actual)==normalized(expected)
    assert [order['id'] for order in actual]==ids
    async with Session.begin() as session:
        with pytest.raises(Fault) as failure:await commerce.get_orders(session,client.user,ids+[foreign['id']])
        assert failure.value.status==403
