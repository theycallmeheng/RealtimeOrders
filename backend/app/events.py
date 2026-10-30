"""Transactional topic sequencer and durable outbox. One application worker."""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from sqlalchemy import select, update, or_, func, event as sql_event
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.dialects.mysql import insert
from .db import T, Session, now, uid, add, public, one

log = logging.getLogger(__name__)
outbox_ready = asyncio.Event()

@sql_event.listens_for(SyncSession,'after_commit')
def wake_committed_outbox(session):
    if session.info.pop('committed_outbox_pending',False):
        # A signal is only a hint. The worker still reads committed durable rows.
        try:asyncio.get_running_loop()
        except RuntimeError:return
        outbox_ready.set()

@sql_event.listens_for(SyncSession,'after_rollback')
def forget_rolled_back_outbox(session):
    session.info.pop('committed_outbox_pending',None)

def emit(s, topic, kind, payload, entity=None, version=None):
    s.info.setdefault('events', []).append((topic, kind, public(payload), entity, version))

async def flush_events(s):
    pending = s.info.pop('events', [])
    if not pending: return
    heads = {}
    for topic in sorted({e[0] for e in pending}):
        t = T['stream_heads']
        await s.execute(insert(t).values(topic=topic, last_seq=0).on_duplicate_key_update(topic=topic))
        heads[topic] = (await s.execute(select(t.c.last_seq).where(t.c.topic == topic).with_for_update())).scalar_one()
    event_rows=[];outbox_rows=[]
    for topic, kind, payload, entity, version in pending:
        heads[topic] += 1
        event = uid()
        event_rows.append(dict(topic=topic, seq=heads[topic], event_id=event, event_type=kind,
                  entity_id=entity, entity_version=version, payload=payload, created_at=now()))
        outbox_rows.append(dict(event_id=event, state='PENDING', attempts=0, next_attempt_at=now(), created_at=now()))
    await s.execute(T['stream_events'].insert(),event_rows)
    await s.execute(T['outbox'].insert(),outbox_rows)
    for topic, seq in heads.items():
        await s.execute(update(T['stream_heads']).where(T['stream_heads'].c.topic == topic).values(last_seq=seq))
    s.info['committed_outbox_pending']=True

def event_wire(e):
    return {'v': 1, 'type': 'EVENT', 'topic': e['topic'], 'seq': str(e['seq']),
            'eventId': e['event_id'], 'eventType': e['event_type'], 'entityId': e['entity_id'],
            'entityVersion': str(e['entity_version']) if e['entity_version'] else None, 'payload': e['payload']}

@dataclass(frozen=True,slots=True)
class EncodedFrame:
    message: dict
    text: str
    size: int

def encode_frame(message,size=None):
    text=json.dumps(message,ensure_ascii=False,separators=(',',':'))
    return EncodedFrame(message,text,len(text.encode()) if size is None else size)

class Subscriber:
    def __init__(self, topics, user_id, session_id=None):
        self.topics, self.user_id = set(topics), user_id
        self.session_id=session_id
        self.queue = asyncio.Queue(128)
        self.bytes = 0
        self.slow = False

    def put(self, message, size=None):
        self.put_frame(encode_frame(message,size))

    def put_frame(self,frame):
        if self.bytes + frame.size > 512*1024 or self.queue.full():
            self.slow = True
            return
        self.bytes += frame.size
        self.queue.put_nowait(frame)

    async def get_frame(self):
        frame=await self.queue.get()
        self.bytes-=frame.size
        return frame

    async def get(self):
        return (await self.get_frame()).message

class Hub:
    def __init__(self):
        self.clients=set()
        self.by_topic={}

    def register(self,client):
        self.clients.add(client)
        for topic in client.topics: self.by_topic.setdefault(topic,set()).add(client)

    def unregister(self,client):
        self.clients.discard(client)
        for topic in client.topics:
            subscribers=self.by_topic.get(topic)
            if subscribers is not None:
                subscribers.discard(client)
                if not subscribers: self.by_topic.pop(topic,None)

    def publish(self, event):
        subscribers=self.by_topic.get(event['topic'])
        if not subscribers: return
        frame=encode_frame(event_wire(event))
        for client in tuple(subscribers): client.put_frame(frame)

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
        pending=[]
        failed=False
        outbox_ready.clear()
        try:
            async with Session.begin() as s:
                o, e = T['outbox'], T['stream_events']
                pending = (await s.execute(select(e, o.c.id.label('outbox_id')).join(o, o.c.event_id == e.c.event_id)
                    .where(o.c.state != 'PUBLISHED', o.c.next_attempt_at <= now()).order_by(o.c.id).limit(200)
                    .with_for_update(skip_locked=True))).mappings().all()
                for index,event in enumerate(pending):
                    # Only committed events are visible here. Duplicate delivery after crash is safe by seq.
                    hub.publish(dict(event))
                    if index%16==15: await asyncio.sleep(0)
                if pending:
                    await s.execute(update(o).where(o.c.id.in_([event['outbox_id'] for event in pending]))
                                    .values(state='PUBLISHED',published_at=now()))
            await notification_batch()
        except asyncio.CancelledError: raise
        except Exception:
            failed=True
            log.exception('outbox_worker_failed')
        if failed:await asyncio.sleep(.1)
        elif pending:await asyncio.sleep(0)
        else:
            # Poll also covers events committed by another process and lost hints.
            try:await asyncio.wait_for(outbox_ready.wait(),.02)
            except asyncio.TimeoutError:pass

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
        for id in users:
            if job['kind']=='PRODUCT_OPENED':
                from .commerce import catalog
                user=await one(s,'users',T['users'].c.id==id)
                if not await catalog(s,user,offer_ids=[job['payload']['offerId']]): continue
            await notify(s, id, job['kind'], job['payload'], job['source_fact_id'])
        await s.execute(update(j).where(j.c.id == job['id']).values(
            after_user_id=users[-1] if users else job['after_user_id'],
            state='COMPLETED' if len(users) < 100 else 'PENDING',
            completed_at=now() if len(users) < 100 else None))
        await flush_events(s)
