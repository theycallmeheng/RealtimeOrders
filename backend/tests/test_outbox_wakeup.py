"""Commit notifications accelerate publication without bypassing persistence."""
import asyncio
import json
from sqlalchemy import func,select
from app import events
from app.db import Session,T,uid
from test_integration import socket as open_socket,sync_messages


async def test_wakeup_is_emitted_only_after_committed_event(clients):
    topic='user:'+clients[1].user['id']
    events.outbox_ready.clear()
    async with Session.begin() as session:
        events.emit(session,topic,'COMMIT_WAKE_PROBE',{'marker':uid()})
        await events.flush_events(session)
        assert not events.outbox_ready.is_set()
    assert events.outbox_ready.is_set()
    events.outbox_ready.clear()


async def test_rollback_does_not_wake_or_persist_outbox(clients):
    topic='rollback-wake:'+uid()
    events.outbox_ready.clear()
    async with Session() as session:
        await session.begin()
        events.emit(session,topic,'ROLLBACK_WAKE_PROBE',{})
        await events.flush_events(session)
        assert not events.outbox_ready.is_set()
        await session.rollback()
        assert not events.outbox_ready.is_set()
        # Reusing a session for an unrelated commit must not retain the hint.
        async with session.begin():
            assert not (await session.execute(select(func.count()).select_from(T['stream_events'])
                        .where(T['stream_events'].c.topic==topic))).scalar_one()
        assert not events.outbox_ready.is_set()


async def test_worker_finds_commits_without_a_local_hint(clients):
    # This writer is a separate process from the real backend's event loop.
    client=clients[1]
    ws=await open_socket(client)
    marker=uid()
    try:
        await sync_messages(ws)
        async with Session.begin() as session:
            events.emit(session,'user:'+client.user['id'],'FALLBACK_WAKE_PROBE',{'marker':marker})
            await events.flush_events(session)
        events.outbox_ready.clear()
        while True:
            message=json.loads(await asyncio.wait_for(ws.recv(),3))
            if message['type']=='PING':await ws.send(json.dumps({'v':1,'type':'PONG'}))
            if message.get('eventType')=='FALLBACK_WAKE_PROBE':
                assert message['payload']['marker']==marker
                break
    finally:await ws.close()
