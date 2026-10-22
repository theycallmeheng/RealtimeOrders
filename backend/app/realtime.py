import asyncio
import json
import time
from contextlib import suppress
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from .config import settings
from .db import T, Session, engine, now, one, rows, public, check, Fault
from . import auth, commerce, chat
from .events import hub, Subscriber, event_wire, flush_events

async def topics_for(s,user):
    return ['user:'+user['id'],'admin:ops'] if user['role']=='ADMIN' else ['user:'+user['id'],'catalog:'+user['group_id']]

async def snapshot(s,user):
    data={'user':auth.profile(user),'offers':await commerce.catalog(s,user,admin=user['role']=='ADMIN')}
    t=T['orders']
    q=select(t.c.id).order_by(t.c.created_at.desc(),t.c.id.desc()).limit(50)
    if user['role']!='ADMIN': q=q.where(t.c.customer_id==user['id'])
    data['orders']=[await commerce.get_order(s,user,id) for id in (await s.execute(q)).scalars()]
    data['notifications']=await rows(s,'notifications',T['notifications'].c.user_id==user['id'],limit=50,
                                     order=T['notifications'].c.created_at.desc())
    data['subscriptions']=await rows(s,'product_subscriptions',T['product_subscriptions'].c.user_id==user['id'],limit=500)
    return public(data)

async def synchronize(ws,user,sub,hello):
    # Register live first, then read data AND heads from a repeatable-read snapshot.
    async with engine.connect() as conn:
        conn=await conn.execution_options(isolation_level='REPEATABLE READ')
        async with Session(bind=conn) as s:
            async with s.begin():
                # First consistent SELECT establishes the snapshot. Never use FOR UPDATE here.
                heads={r['topic']:int(r['last_seq']) for r in await rows(s,'stream_heads',T['stream_heads'].c.topic.in_(sub.topics))}
                heads={t:heads.get(t,0) for t in sub.topics}
                cursors=hello.get('lastSeq',{})
                replay=hello.get('hasModel') is True and isinstance(cursors,dict)
                events=[]
                if replay:
                    for topic in sorted(sub.topics):
                        try: seq=int(cursors.get(topic,-1))
                        except (ValueError,TypeError): replay=False; break
                        if not 0<=seq<=heads[topic] or heads[topic]-seq>500: replay=False; break
                        data=await rows(s,'stream_events',T['stream_events'].c.topic==topic,T['stream_events'].c.seq>seq,
                                        T['stream_events'].c.seq<=heads[topic],limit=501,order=T['stream_events'].c.seq)
                        if len(data)!=heads[topic]-seq: replay=False; break
                        events.extend(event_wire(e) for e in data)
                    if len(events)>500 or len(json.dumps(events).encode())>256*1024: replay=False
                model=None if replay else await snapshot(s,user)
    await ws.send_json({'v':1,'type':'SYNC_BEGIN','mode':'REPLAY' if replay else 'SNAPSHOT'})
    if replay:
        for event in events: await ws.send_json(event)
    else:
        encoded=json.dumps(model,ensure_ascii=False,separators=(',',':'))
        # Chunk by characters conservatively: <=32KiB even with four-byte Unicode.
        chunks=[encoded[i:i+7000] for i in range(0,len(encoded),7000)]
        for i,chunk in enumerate(chunks):
            await ws.send_json({'v':1,'type':'SNAPSHOT_CHUNK','index':i,'total':len(chunks),'data':chunk})
    await ws.send_json({'v':1,'type':'SYNC_END','heads':{k:str(v) for k,v in heads.items()}})
    return heads

async def serve_socket(ws:WebSocket):
    if ws.headers.get('origin')!=settings.app_origin:
        await ws.close(code=1008); return
    raw=ws.cookies.get('ro_session')
    try:
        async with Session.begin() as s:
            user=await auth.authenticate(s,raw)
            topics=await topics_for(s,user)
            session_id=s.info['authenticated_session_id']
    except Fault:
        await ws.close(code=1008); return
    await ws.accept()
    sub=Subscriber(topics,user['id'],session_id); hub.clients.add(sub)
    receive=None; get=None
    try:
        first=await asyncio.wait_for(ws.receive_text(),10)
        if len(first.encode())>65536: await ws.close(code=1009); return
        try: hello=json.loads(first)
        except ValueError: raise Fault('INVALID_JSON','Thông điệp JSON không hợp lệ')
        check(isinstance(hello,dict) and hello.get('type')=='HELLO' and hello.get('v')==1,
              'PROTOCOL_VERSION','Yêu cầu giao thức phiên bản 1')
        await ws.send_json({'v':1,'type':'WELCOME','topics':topics,'heartbeatSeconds':15})
        heads=await synchronize(ws,user,sub,hello)
        receive=asyncio.create_task(ws.receive_text()); get=asyncio.create_task(sub.get())
        last_seen=time.monotonic(); next_heartbeat=last_seen+15
        while True:
            if sub.slow: await ws.close(code=1013,reason='Client nhận chậm; kết nối lại để đồng bộ.'); return
            done,_=await asyncio.wait([receive,get],timeout=max(.01,next_heartbeat-time.monotonic()),return_when=asyncio.FIRST_COMPLETED)
            if time.monotonic()>=next_heartbeat:
                if time.monotonic()-last_seen>45: await ws.close(code=1001); return
                await ws.send_json({'v':1,'type':'PING'}); next_heartbeat=time.monotonic()+15
            if get in done:
                event=get.result(); get=asyncio.create_task(sub.get())
                if event.get('type')=='SESSION_REVOKED':
                    await ws.send_json(event);await ws.close(code=1008);return
                if event.get('eventType')=='SESSION_REVOKED':
                    await ws.send_json({'v':1,'type':'SESSION_REVOKED',**event['payload']}); await ws.close(code=1008); return
                topic=event['topic']; seq=int(event['seq'])
                if seq<=heads.get(topic,0): continue
                if seq!=heads.get(topic,0)+1:
                    heads=await synchronize(ws,user,sub,{'hasModel':False})
                    continue
                heads[topic]=seq; await ws.send_json(event)
            if receive in done:
                raw_message=receive.result(); receive=asyncio.create_task(ws.receive_text()); last_seen=time.monotonic()
                if len(raw_message.encode())>65536: await ws.close(code=1009); return
                try:
                    message=json.loads(raw_message)
                    check(isinstance(message,dict) and message.get('v')==1,'INVALID_MESSAGE','Thông điệp không hợp lệ')
                    kind=message.get('type')
                    if kind=='PONG': continue
                    if kind=='PING': await ws.send_json({'v':1,'type':'PONG'}); continue
                    if kind=='RESYNC_REQUEST':
                        await auth.rate('resync:'+user['id'],10,60)
                        async with Session.begin() as s:await auth.authenticate(s,raw)
                        heads=await synchronize(ws,user,sub,message); continue
                    if kind=='SESSION_ACTIVITY':
                        await auth.rate('activity:'+user['id'],10,60)
                        async with Session.begin() as s: await auth.authenticate(s,raw,activity=True)
                        continue
                    check(kind=='CHAT_SEND','INVALID_MESSAGE','Lệnh không được hỗ trợ')
                    await auth.rate('chat:'+user['id'],30,60)
                    async with Session.begin() as s:
                        current=await auth.authenticate(s,raw,activity=True)
                        result=await chat.send(s,current,message.get('payload',{}))
                        await flush_events(s)
                    await ws.send_json({'v':1,'type':'ACK','clientMessageId':result['client_message_id'],'payload':result})
                except (ValueError,Fault) as exc:
                    await ws.send_json({'v':1,'type':'ERROR','code':getattr(exc,'code','INVALID_JSON'),
                                        'message':getattr(exc,'message','Thông điệp không hợp lệ')})
    except Fault as exc:
        with suppress(Exception):
            await ws.send_json({'v':1,'type':'ERROR','code':exc.code,'message':exc.message}); await ws.close(code=1008)
    except (WebSocketDisconnect,asyncio.TimeoutError,RuntimeError): pass
    finally:
        hub.clients.discard(sub)
        for task in (receive,get):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError,Exception): await task
