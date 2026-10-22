"""Transactional topic sequencer and durable outbox. One application worker."""
import asyncio
import json
import logging
from datetime import timedelta
from sqlalchemy import select, update, or_, func
from sqlalchemy.dialects.mysql import insert
from .db import T, Session, now, uid, add, public

log = logging.getLogger(__name__)

def emit(s, topic, kind, payload, entity=None, version=None):
    s.info.setdefault('events', []).append((topic, kind, public(payload), entity, version))

async def flush_events(s):
    pending = s.info.pop('events', [])
    heads = {}
    for topic in sorted({e[0] for e in pending}):
        t = T['stream_heads']
        await s.execute(insert(t).values(topic=topic, last_seq=0).on_duplicate_key_update(topic=topic))
        heads[topic] = (await s.execute(select(t.c.last_seq).where(t.c.topic == topic).with_for_update())).scalar_one()
    for topic, kind, payload, entity, version in pending:
        heads[topic] += 1
        event = uid()
        await add(s, 'stream_events', topic=topic, seq=heads[topic], event_id=event, event_type=kind,
                  entity_id=entity, entity_version=version, payload=payload, created_at=now())
        await add(s, 'outbox', event_id=event, state='PENDING', attempts=0, next_attempt_at=now(), created_at=now())
    for topic, seq in heads.items():
        await s.execute(update(T['stream_heads']).where(T['stream_heads'].c.topic == topic).values(last_seq=seq))

def event_wire(e):
    return {'v': 1, 'type': 'EVENT', 'topic': e['topic'], 'seq': str(e['seq']),
            'eventId': e['event_id'], 'eventType': e['event_type'], 'entityId': e['entity_id'],
            'entityVersion': str(e['entity_version']) if e['entity_version'] else None, 'payload': e['payload']}

class Subscriber:
    def __init__(self, topics, user_id, session_id=None):
        self.topics, self.user_id = set(topics), user_id
        self.session_id=session_id
        self.queue = asyncio.Queue(128)
        self.bytes = 0
        self.slow = False

    def put(self, message, size=None):
        if size is None: size = len(json.dumps(message, ensure_ascii=False).encode())
        if self.bytes + size > 512*1024 or self.queue.full():
            self.slow = True
            return
        self.bytes += size
        self.queue.put_nowait((message, size))

    async def get(self):
        message, size = await self.queue.get()
        self.bytes -= size
        return message

class Hub:
    def __init__(self): self.clients = set()
    def publish(self, event):
        wire=event_wire(event)
        size=len(json.dumps(wire,ensure_ascii=False).encode())
        for client in tuple(self.clients):
            if event['topic'] in client.topics: client.put(wire,size)

hub = Hub()

async def session_monitor():
    """Validate active sockets together; avoid thousands of per-heartbeat DB queries."""
    from .config import settings
    while True:
        await asyncio.sleep(2)
        clients=tuple(hub.clients)
        if not clients: continue
        try:
            t,u=T['sessions'],T['users']
            async with Session.begin() as s:
                result=(await s.execute(select(t.c.id).join(u,t.c.user_id==u.c.id)
                    .where(t.c.id.in_({c.session_id for c in clients}),t.c.revoked_at==None,u.c.status=='ACTIVE',
                           t.c.security_version==u.c.security_version,t.c.absolute_expires_at>now(),
                           t.c.last_activity_at>now()-timedelta(seconds=settings.idle_seconds)))).scalars().all()
            valid=set(result)
            for client in clients:
                if client.session_id not in valid:client.put({'v':1,'type':'SESSION_REVOKED','message':'Phiên đã hết hạn hoặc bị thu hồi.'})
        except asyncio.CancelledError:raise
        except Exception:log.error('session_monitor_unavailable')

async def outbox_worker():
    while True:
        try:
            async with Session.begin() as s:
                o, e = T['outbox'], T['stream_events']
                pending = (await s.execute(select(e, o.c.id.label('outbox_id')).join(o, o.c.event_id == e.c.event_id)
                    .where(o.c.state != 'PUBLISHED', o.c.next_attempt_at <= now()).order_by(o.c.id).limit(200)
                    .with_for_update(skip_locked=True))).mappings().all()
                for event in pending:
                    # Only committed events are visible here. Duplicate delivery after crash is safe by seq.
                    hub.publish(dict(event))
                    await s.execute(update(o).where(o.c.id == event['outbox_id']).values(state='PUBLISHED', published_at=now()))
            await notification_batch()
        except asyncio.CancelledError: raise
        except Exception: log.exception('outbox_worker_failed')
        await asyncio.sleep(.05 if pending else .1)

async def notify(s, user_id, kind, payload, fact=None):
    fact = fact or uid()
    id = uid()
    t = T['notifications']
    result = await s.execute(insert(t).values(id=id, user_id=user_id, source_event_id=fact, kind=kind,
                    payload=public(payload), created_at=now()).on_duplicate_key_update(id=t.c.id))
    if result.rowcount == 1:
        emit(s, 'user:'+user_id, 'NOTIFICATION', {'id': id, 'kind': kind, 'payload': payload})

async def notification_batch():
    async with Session.begin() as s:
        j = T['notification_jobs']
        job = (await s.execute(select(j).where(j.c.state != 'COMPLETED').order_by(j.c.created_at).limit(1)
                               .with_for_update(skip_locked=True))).mappings().first()
        if not job: return
        sub = T['product_subscriptions']
        q = select(sub.c.user_id).where(sub.c.product_id == job['product_id'])
        if job['after_user_id']: q = q.where(sub.c.user_id > job['after_user_id'])
        users = (await s.execute(q.order_by(sub.c.user_id).limit(100))).scalars().all()
        for id in users: await notify(s, id, job['kind'], job['payload'], job['source_fact_id'])
        await s.execute(update(j).where(j.c.id == job['id']).values(
            after_user_id=users[-1] if users else job['after_user_id'],
            state='COMPLETED' if len(users) < 100 else 'PENDING',
            completed_at=now() if len(users) < 100 else None))
        await flush_events(s)
