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

# Leave DB capacity available for live operations during a reconnect wave.
sync_slots=asyncio.Semaphore(8)

async def receive_text_frame(ws):
    frame=await ws.receive()
    if frame['type']=='websocket.disconnect':
        raise WebSocketDisconnect(frame.get('code',1000))
    check(frame.get('text') is not None,'INVALID_MESSAGE','Chỉ nhận thông điệp JSON dạng văn bản')
    return frame['text']

class SocketClosing(Exception):
    def __init__(self,code,reason=''):
        self.code,self.reason=code,reason

async def topics_for(s,user):
    return ['user:'+user['id'],'admin:ops'] if user['role']=='ADMIN' else ['user:'+user['id'],'catalog:'+user['group_id']]

async def snapshot(s,user):
    data={'user':auth.profile(user),'offers':await commerce.catalog(s,user,admin=user['role']=='ADMIN')}
    t=T['orders']
    q=select(t.c.id).order_by(t.c.created_at.desc(),t.c.id.desc()).limit(50)
    if user['role']!='ADMIN': q=q.where(t.c.customer_id==user['id'])
    data['orders']=await commerce.get_orders(s,user,list((await s.execute(q)).scalars()))
    from .menus import notification_feed
    data['notifications']=await notification_feed(s,user)
    data['subscriptions']=await rows(s,'product_subscriptions',T['product_subscriptions'].c.user_id==user['id'],limit=500)
    return public(data)

async def synchronize(ws,user,sub,hello):
    # Register live first. Bound DB sync work, then release the slot before socket I/O.
    async with sync_slots:
        async with engine.connect() as conn:
            conn=await conn.execution_options(isolation_level='REPEATABLE READ')
            async with Session(bind=conn) as s:
                async with s.begin():
                    # Revalidate after admission; this first SELECT establishes the RR snapshot.
                    user=await auth.authenticate(s,ws.cookies.get('ro_session'))
                    check(set(await topics_for(s,user))==sub.topics,'SESSION_EXPIRED','Quyền phiên đã thay đổi',401)
                    heads={r['topic']:int(r['last_seq']) for r in await rows(s,'stream_heads',T['stream_heads'].c.topic.in_(sub.topics))}
                    heads={t:heads.get(t,0) for t in sub.topics}
                    from .menus import epoch
                    dataset_epoch=await epoch(s)
                    cursors=hello.get('lastSeq',{})
                    replay=hello.get('hasModel') is True and isinstance(cursors,dict) and hello.get('datasetEpoch')==dataset_epoch
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
    await ws.send_json({'v':1,'type':'SYNC_END','datasetEpoch':dataset_epoch,'heads':{k:str(v) for k,v in heads.items()}})
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
    sub=Subscriber(topics,user['id'],session_id); hub.register(sub)
    tasks=[]
    try:
        first=await asyncio.wait_for(receive_text_frame(ws),10)
        if len(first.encode())>65536: await ws.close(code=1009); return
        try: hello=json.loads(first)
        except (ValueError,RecursionError): raise Fault('INVALID_JSON','Thông điệp JSON không hợp lệ')
        check(isinstance(hello,dict) and hello.get('type')=='HELLO' and hello.get('v')==1,
              'PROTOCOL_VERSION','Yêu cầu giao thức phiên bản 1')
        await ws.send_json({'v':1,'type':'WELCOME','topics':topics,'heartbeatSeconds':15})
        heads=await synchronize(ws,user,sub,hello)
        send_lock=asyncio.Lock()
        last_seen=time.monotonic()

        async def control(message):
            async with send_lock: await ws.send_json(message)

        async def send_events():
            nonlocal heads
            while True:
                frame=await sub.get_frame(); event=frame.message
                if sub.slow: raise SocketClosing(1013,'Client nhận chậm; kết nối lại để đồng bộ.')
                # Keep a complete sync batch and live events on one serialized wire.
                async with send_lock:
                    if event.get('type')=='SESSION_REVOKED':
                        await ws.send_json(event);raise SocketClosing(1008)
                    if event.get('eventType')=='SESSION_REVOKED':
                        await ws.send_json({'v':1,'type':'SESSION_REVOKED',**event['payload']});raise SocketClosing(1008)
                    topic=event['topic']; seq=int(event['seq'])
                    if seq<=heads.get(topic,0): continue
                    if seq!=heads.get(topic,0)+1:
                        heads=await synchronize(ws,user,sub,{'hasModel':False})
                        continue
                    heads[topic]=seq
                    await ws.send_text(frame.text)

        async def receive_commands():
            nonlocal heads,last_seen
            while True:
                raw_message=await receive_text_frame(ws);last_seen=time.monotonic()
                if len(raw_message.encode())>65536: raise SocketClosing(1009)
                try:
                    message=json.loads(raw_message)
                    check(isinstance(message,dict) and message.get('v')==1,'INVALID_MESSAGE','Thông điệp không hợp lệ')
                    kind=message.get('type')
                    if kind=='PONG': continue
                    if kind=='PING': await control({'v':1,'type':'PONG'}); continue
                    if kind=='RESYNC_REQUEST':
                        await auth.rate('resync:'+user['id'],10,60)
                        async with Session.begin() as s:await auth.authenticate(s,raw)
                        async with send_lock: heads=await synchronize(ws,user,sub,message)
                        continue
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
                    await control({'v':1,'type':'ACK','clientMessageId':result['client_message_id'],'payload':result})
                except (ValueError,RecursionError,Fault) as exc:
                    await control({'v':1,'type':'ERROR','code':getattr(exc,'code','INVALID_JSON'),
                                   'message':getattr(exc,'message','Thông điệp không hợp lệ')})

        async def heartbeat():
            while True:
                await asyncio.sleep(15)
                if sub.slow: raise SocketClosing(1013,'Client nhận chậm; kết nối lại để đồng bộ.')
                if time.monotonic()-last_seen>45: raise SocketClosing(1001)
                await control({'v':1,'type':'PING'})

        tasks=[asyncio.create_task(receive_commands()),asyncio.create_task(send_events()),asyncio.create_task(heartbeat())]
        try:
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task in done: task.result()
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    except SocketClosing as exc:
        with suppress(Exception): await ws.close(code=exc.code,reason=exc.reason)
    except Fault as exc:
        with suppress(Exception):
            await ws.send_json({'v':1,'type':'ERROR','code':exc.code,'message':exc.message}); await ws.close(code=1008)
    except (WebSocketDisconnect,asyncio.TimeoutError,RuntimeError): pass
    finally:
        hub.unregister(sub)
