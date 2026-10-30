import asyncio
import json
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select,func
from app.db import Session,T,now,uid,one,change
from app.auth import hashed,csrf
from app.events import Subscriber
from conftest import DATA,ORIGIN,order_body
from test_integration import socket,sync_messages

async def test_duplicate_approval_ack_lost(clients,sale):
    a,c=clients[:2];o=await c.post('/orders',await order_body(c,sale,'2'));key=uid();body={'expectedVersion':'1'}
    results=await asyncio.gather(*[a.request('POST','/admin/orders/'+o['id']+'/approve',body,key) for _ in range(4)])
    assert all(r.status_code==200 for r in results)
    assert len({r.json()['id'] for r in results})==1
    async with Session.begin() as s:
        assert (await one(s,'offers',T['offers'].c.id==sale['id']))['available_qty']==8

async def test_delivery_minimum_and_collective_free(clients,sale):
    c=clients[1];body=await order_body(c,sale,'0.1')
    assert (await c.request('POST','/orders',body)).status_code==400
    options=await c.get('/delivery/options');addr=(await c.get('/me/addresses'))[0]
    policy=next(p for p in options['policies'] if p['method']=='COLLECTIVE' and p['zone_id']==addr['zone_id'])
    slot=options['pickupSlots'][0]
    body.update(deliveryMethod='COLLECTIVE',policyVersion=str(policy['version']),pickupSlotId=slot['id'],pickupSlotVersion=str(slot['version']))
    order=await c.post('/orders',body);assert order['shipping_fee']=='0'

async def test_expired_otp(clients):
    async with httpx.AsyncClient(base_url=ORIGIN,verify=False,headers={'Origin':ORIGIN}) as h:
        phone='+849'+str(int(uid().replace('-','')[:8],16))[:8]
        r=await h.post('/api/v1/auth/registration/otp',json={'phone':phone});assert r.status_code==200,r.text
        c=r.json()
        async with Session.begin() as s:await change(s,'auth_challenges',c['challengeId'],expires_at=now()-timedelta(seconds=1))
        r=await h.post('/api/v1/auth/registration/verify',json={'challengeId':c['challengeId'],'code':c['demoCode']});assert r.json()['error']['code']=='OTP_EXPIRED'

async def test_invalid_json_and_unicode_address_moderation(clients):
    c=clients[2]
    r=await c.http.post('/api/v1/product-requests',headers={'Origin':ORIGIN,'X-CSRF-Token':c.session['csrfToken'],'Content-Type':'application/json'},content=b'{bad}')
    assert r.status_code==400
    addr=(await c.get('/me/addresses'))[0]
    r=await c.request('PATCH','/me/addresses/'+addr['id'],{'expectedVersion':str(addr['version']),'zoneId':addr['zone_id'],
        'recipientName':addr['recipient_name'],'phone':addr['phone_e164'],'addressLine':'Địa chỉ từcấmmẫu bị chặn'})
    assert r.status_code==400 and r.json()['error']['code']=='CONTENT_REJECTED'

async def test_wss_chat_ack_after_persist(clients):
    c=clients[2];conv=await c.get('/conversations/me');ws=await socket(c);await sync_messages(ws)
    id=uid();await ws.send(json.dumps({'v':1,'type':'CHAT_SEND','payload':{'conversationId':conv['id'],'clientMessageId':id,'text':'Chat qua WSS','assetIds':[]}}))
    while True:
        m=json.loads(await asyncio.wait_for(ws.recv(),15))
        if m['type']=='PING':await ws.send(json.dumps({'v':1,'type':'PONG'}))
        if m['type']=='ACK':break
    async with Session.begin() as s:
        saved=await one(s,'messages',T['messages'].c.client_message_id==id,T['messages'].c.sender_id==c.user['id'])
        assert saved['id']==m['payload']['id']
    await ws.close()

async def test_wss_resync_fallback_and_frame_limit(clients):
    ws=await socket(clients[1],hasModel=True,lastSeq={'wrong':'999999999999'})
    data=await sync_messages(ws);assert next(m for m in data if m['type']=='SYNC_BEGIN')['mode']=='SNAPSHOT'
    await ws.send('x'*70000)
    with pytest.raises(Exception):await ws.recv()
    await ws.close()

async def test_idle_timeout_not_extended_by_reads(clients):
    c=clients[2]
    # Add a separate test session so other cases keep their active fixture sessions.
    raw='test-session-'+uid()
    from app.db import add
    async with Session.begin() as s:
        user=await one(s,'users',T['users'].c.id==c.user['id'])
        await add(s,'sessions',id=uid(),user_id=user['id'],token_hash=hashed(raw),security_version=user['security_version'],
                  created_at=now()-timedelta(hours=2),last_activity_at=now()-timedelta(minutes=31),absolute_expires_at=now()+timedelta(hours=2))
    async with httpx.AsyncClient(base_url=ORIGIN,verify=False,headers={'Cookie':'ro_session='+raw}) as h:
        r=await h.get('/api/v1/auth/session');assert r.status_code==401

def test_slow_client_queue_bounded():
    subscriber=Subscriber(['catalog:test'],'user')
    for i in range(1000):subscriber.put({'payload':'x'*10000,'seq':str(i)})
    assert subscriber.slow and subscriber.queue.qsize()<=128 and subscriber.bytes<=512*1024

async def test_subscriber_notification_job(clients,sale):
    a,c=clients[:2];await c.post('/subscriptions/products/'+sale['product_id'],{})
    r=await a.request('PATCH','/admin/offers/'+sale['id'],{'expectedVersion':'1','status':'CLOSED'});assert r.status_code==200,r.text
    r=await a.request('PATCH','/admin/offers/'+sale['id'],{'expectedVersion':str(r.json()['version']),'status':'OPEN'});assert r.status_code==200,r.text
    found=False
    for _ in range(40):
        data=await c.get('/notifications')
        if any(n['kind']=='PRODUCT_OPENED' and n['payload'].get('offerId')==sale['id'] for n in data):found=True;break
        await asyncio.sleep(.1)
    assert found

async def test_topic_sequence_cannot_skip_uncommitted_event(clients):
    from app.events import emit,flush_events
    topic='test:'+uid();prepared=asyncio.Event();release=asyncio.Event();b_started=asyncio.Event()
    async def a():
        async with Session.begin() as s:
            emit(s,topic,'TEST_A',{'order':'first'});await flush_events(s);prepared.set();await release.wait()
    async def b():
        await prepared.wait();b_started.set()
        async with Session.begin() as s:
            emit(s,topic,'TEST_B',{'order':'second'});await flush_events(s)
    first=asyncio.create_task(a());second=asyncio.create_task(b());await b_started.wait()
    try:
        with pytest.raises(asyncio.TimeoutError):await asyncio.wait_for(asyncio.shield(second),.1)
    finally:release.set()
    await asyncio.gather(first,second)
    async with Session.begin() as s:
        events=(await s.execute(select(T['stream_events']).where(T['stream_events'].c.topic==topic).order_by(T['stream_events'].c.seq))).mappings().all()
    assert [(e['seq'],e['event_type']) for e in events]==[(1,'TEST_A'),(2,'TEST_B')]




async def test_socket_session_monitor_revokes_idle_session(clients):
    import secrets,ssl,websockets
    from app.db import add
    raw=secrets.token_urlsafe(48);id=uid()
    async with Session.begin() as s:
        user=await one(s,'users',T['users'].c.id==clients[2].user['id'])
        await add(s,'sessions',id=id,user_id=user['id'],token_hash=hashed(raw),security_version=user['security_version'],
                  created_at=now(),last_activity_at=now(),absolute_expires_at=now()+timedelta(hours=2))
    ws=await websockets.connect('wss://localhost:3443/ws',origin=ORIGIN,ssl=ssl._create_unverified_context(),additional_headers={'Cookie':'ro_session='+raw})
    await ws.send(json.dumps({'v':1,'type':'HELLO','hasModel':False}));await sync_messages(ws)
    async with Session.begin() as s:await change(s,'sessions',id,last_activity_at=now()-timedelta(minutes=31))
    message=json.loads(await asyncio.wait_for(ws.recv(),6));assert message['type']=='SESSION_REVOKED'
    await ws.close()
