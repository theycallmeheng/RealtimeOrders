"""Controlled local load. Creates isolated test identities, saves only aggregate metrics.

Run from project root with .venv Python; backend must be up, one worker.
The target is real distinct authenticated WSS connections, not fictitious sessions.
"""
import argparse
import asyncio
import hashlib
import json
import os
import secrets
import ssl
import statistics
import sys
import time
from pathlib import Path
from datetime import timedelta
import httpx
import psutil
import websockets
from sqlalchemy import select

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.db import T,Session,engine,reflect,now,uid,add
from app.config import settings
from app.auth import hashed

def percentile(data,p):
    return round(sorted(data)[min(len(data)-1,int((len(data)-1)*p))],2) if data else None

async def run(args):
    await reflect()
    tag=uid()[:8]; identities=[]
    async with Session.begin() as s:
        group=(await s.execute(select(T['customer_groups'].c.id).where(T['customer_groups'].c.code=='WORKER'))).scalar_one()
        template=(await s.execute(select(T['users'].c.password_hash).where(T['users'].c.role=='CUSTOMER').limit(1))).scalar_one()
        users=[];sessions=[]
        for n in range(args.clients):
            id=uid();raw=secrets.token_urlsafe(48)
            users.append(dict(id=id,phone_e164='+99'+str(int(tag,16)).zfill(10)[-8:]+str(n).zfill(4),password_hash=template,
                display_name=f'LOAD-{tag}-{n}',role='CUSTOMER',status='ACTIVE',group_id=group,phone_verified_at=now(),
                security_version=1,version=1,created_at=now(),updated_at=now()))
            sessions.append(dict(id=uid(),user_id=id,token_hash=hashed(raw),security_version=1,created_at=now(),last_activity_at=now(),
                absolute_expires_at=now()+timedelta(hours=2)))
            identities.append((id,raw))
        await s.execute(T['users'].insert(),users)
        await s.execute(T['sessions'].insert(),sessions)
    context=ssl._create_unverified_context(); connected=[]; connect_ms=[];event_ms=[];api_ms=[];failures=[];received=0;bytes_in=0;messages_in=0
    semaphore=asyncio.Semaphore(args.ramp_concurrency)
    stop=asyncio.Event();sent={};monitor=[];planned_disconnects=set()
    processes=[p for p in psutil.process_iter(['pid','name','cmdline']) if p.info['name'].lower() in ('python.exe','node.exe','mysqld.exe') and any(x in ' '.join(p.info['cmdline'] or []) for x in ['uvicorn app.main','proxy.mjs','next start','RealtimeOrders-runtime'])]
    for p in processes:
        try:p.cpu_percent()
        except psutil.Error:pass
    async def read_loop(ws,index):
        nonlocal received,bytes_in,messages_in
        try:
            async for raw in ws:
                bytes_in+=len(raw.encode());messages_in+=1;m=json.loads(raw)
                if m['type']=='PING':await ws.send(json.dumps({'v':1,'type':'PONG'}))
                if m['type']=='EVENT' and m.get('eventType')=='LOAD_PROBE':
                    probe=m['payload']['probe'];start=sent.get(probe)
                    if start is not None:event_ms.append((time.perf_counter()-start)*1000);received+=1
        except Exception as exc:
            if not stop.is_set() and index not in planned_disconnects:
                failures.append({'phase':'receive','type':type(exc).__name__})
    async def connect(index,identity):
        nonlocal bytes_in,messages_in
        async with semaphore:
            start=time.perf_counter()
            ws=None
            try:
                ws=await websockets.connect(args.url.replace('https:','wss:')+'/ws',origin=settings.app_origin,
                    additional_headers={'Cookie':'ro_session='+identity[1]},ssl=context,open_timeout=60,max_size=65536,ping_interval=None)
                await ws.send(json.dumps({'v':1,'type':'HELLO','hasModel':False}))
                while True:
                    raw=await asyncio.wait_for(ws.recv(),60);bytes_in+=len(raw.encode());messages_in+=1;m=json.loads(raw)
                    if m['type']=='SYNC_END':break
                    if m['type']=='ERROR':raise RuntimeError(m['code'])
                connect_ms.append((time.perf_counter()-start)*1000)
                connected.append((index,ws,asyncio.create_task(read_loop(ws,index))))
                return True
            except asyncio.CancelledError:
                if ws is not None:await ws.close()
                raise
            except Exception as exc:
                failures.append({'phase':'connect','type':type(exc).__name__})
                if ws is not None:await ws.close()
                return False
    started=time.perf_counter()
    await asyncio.gather(*(connect(i,identity) for i,identity in enumerate(identities)))
    ready_seconds=time.perf_counter()-started
    initial_count=len(connected)
    recovery_ms=[];recovery_indices=[]
    print(f'Connected and synchronized: {len(connected)}/{args.clients}; active phase {args.seconds}s',flush=True)
    from app.events import emit,flush_events
    async with httpx.AsyncClient(base_url=args.url,verify=False,timeout=20) as client:
        async def requests():
            n=0
            while not stop.is_set():
                identity=identities[n%len(identities)];n+=1;start=time.perf_counter()
                try:
                    response=await client.get('/api/v1/catalog/offers',headers={'Cookie':'ro_session='+identity[1]})
                    if response.status_code!=200:failures.append({'phase':'http','status':response.status_code})
                    else:api_ms.append((time.perf_counter()-start)*1000)
                except Exception as exc:failures.append({'phase':'http','type':type(exc).__name__})
                await asyncio.sleep(max(0,1/args.rps-(time.perf_counter()-start)))
        async def probes():
            while not stop.is_set():
                id=uid();sent[id]=time.perf_counter()
                async with Session.begin() as s:
                    emit(s,'catalog:'+group,'LOAD_PROBE',{'probe':id});await flush_events(s)
                await asyncio.sleep(2)
        async def samples():
            while not stop.is_set():
                sample={'atSeconds':round(time.perf_counter()-started,2),'availableRamMiB':round(psutil.virtual_memory().available/1048576,1),'processes':[]}
                for p in processes:
                    try:sample['processes'].append({'pid':p.pid,'name':p.name(),'cpuPercent':p.cpu_percent(),'rssMiB':round(p.memory_info().rss/1048576,1)})
                    except psutil.Error:pass
                monitor.append(sample);await asyncio.sleep(2)
        async def recovery():
            if not args.reconnect_fraction:return
            await asyncio.sleep(20)
            count=int(initial_count*args.reconnect_fraction)
            chosen=connected[:count]
            planned_disconnects.update(index for index,_,_ in chosen)
            await asyncio.gather(*(ws.close() for _,ws,_ in chosen),return_exceptions=True)
            await asyncio.gather(*(task for _,_,task in chosen),return_exceptions=True)
            await asyncio.sleep(5)
            async def resume(index):
                planned_disconnects.discard(index)
                start=time.perf_counter()
                if await connect(index,identities[index]):
                    recovery_ms.append((time.perf_counter()-start)*1000);recovery_indices.append(index)
            await asyncio.gather(*(resume(index) for index,_,_ in chosen))
        tasks=[asyncio.create_task(f()) for f in (requests,probes,samples)]
        recovery_task=asyncio.create_task(recovery())
        await asyncio.sleep(args.seconds);stop.set()
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if not recovery_task.done():
            failures.append({'phase':'recovery','type':'INCOMPLETE_AT_DEADLINE'});recovery_task.cancel()
        await asyncio.gather(recovery_task,return_exceptions=True)
        await asyncio.sleep(3)
    active_before_close=sum(not t.done() for _,_,t in connected)
    active_identities={index for index,_,task in connected if not task.done()}
    await asyncio.gather(*(ws.close() for _,ws,_ in connected),return_exceptions=True)
    await asyncio.gather(*(t for _,_,t in connected),return_exceptions=True)
    result={'timestampUtc':now().isoformat()+'Z','tag':tag,'variant':args.label,'requestedDistinctCustomers':args.clients,'synchronizedConnections':initial_count,
        'activeAtEnd':active_before_close,'distinctActiveCustomersAtEnd':len(active_identities),
        'rampSeconds':round(ready_seconds,2),'measurementSeconds':args.seconds,'requestedCatalogRps':args.rps,
        'successfulCatalogRequests':len(api_ms),'businessOrderRps':0,'probeDeliveries':received,'probeCount':len(sent),
        'connectP50Ms':percentile(connect_ms,.5),'connectP95Ms':percentile(connect_ms,.95),
        'catalogP50Ms':percentile(api_ms,.5),'catalogP95Ms':percentile(api_ms,.95),
        'eventP50Ms':percentile(event_ms,.5),'eventP95Ms':percentile(event_ms,.95),
        'receivedMessages':messages_in,'receivedUtf8Bytes':bytes_in,'errors':failures,'resourceSamples':monitor,
        'drainSeconds':3,'totalHandshakes':len(connected),'reconnectFraction':args.reconnect_fraction,'recoveredConnections':len(recovery_ms),
        'recoveryIdentityIndices':recovery_indices,
        'recoveryP50Ms':percentile(recovery_ms,.5),'recoveryP95Ms':percentile(recovery_ms,.95),
        'environment':{'platform':sys.platform,'python':sys.version.split()[0],'cpuLogical':psutil.cpu_count(),
            'ramGiB':round(psutil.virtual_memory().total/1073741824,2),'topology':'load generator, HTTPS proxy, FastAPI and MySQL on same Windows PC'},
        'limitations':['Read and realtime fanout scenario; not 2000 simultaneous approvals.','Loopback test, not proof of WAN/LAN multi-machine capacity.','CPU percent per process can exceed 100 on multicore.']}
    folder=ROOT/'evidence/load';folder.mkdir(exist_ok=True,parents=True)
    (folder/f'{args.clients}-{tag}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('resourceSamples','environment','limitations')},ensure_ascii=False),flush=True)
    # Keep benchmark users for traceability, revoke generated sessions immediately.
    async with Session.begin() as s:
        await s.execute(T['sessions'].update().where(T['sessions'].c.user_id.in_([i[0] for i in identities])).values(revoked_at=now()))
        await s.execute(T['users'].update().where(T['users'].c.id.in_([i[0] for i in identities])).values(status='DELETED'))
    await engine.dispose()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--clients',type=int,default=100);parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--rps',type=float,default=10);parser.add_argument('--ramp-concurrency',type=int,default=30);parser.add_argument('--url',default='https://localhost:3443')
    parser.add_argument('--label',default='batched-session-check');parser.add_argument('--reconnect-fraction',type=float,default=0)
    args=parser.parse_args();assert 1<=args.clients<=2500 and 5<=args.seconds<=600 and 0<args.rps<=100
    asyncio.run(run(args))
