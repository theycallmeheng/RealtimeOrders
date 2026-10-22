"""WSS delta vs HTTPS polling of the same catalog, real distinct identities.
Payload-byte comparison excludes HTTP/TLS framing; not a packet capture.
Default full run: 3 repeats x (15s warmup + 60s measured) per mode.
"""
import argparse
import asyncio
import csv
import json
import secrets
import ssl
import sys
import time
from datetime import timedelta
from pathlib import Path
import httpx
import websockets
from sqlalchemy import select
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.db import T,Session,engine,reflect,now,uid,one,add,change,public
from app import admin
from app.auth import hashed
from app.events import flush_events
from app.config import settings
from load_test import percentile

async def main(args):
    await reflect();tag=uid()[:8];actors=[];offers=[];groups=[];admin_user=None
    async with Session.begin() as s:
        groups=[dict(r) for r in (await s.execute(select(T['customer_groups']))).mappings()]
        admin_user=await one(s,'users',T['users'].c.role=='ADMIN')
        product=await one(s,'products',T['products'].c.active==True)
        for n in range(args.offers):
            offer=await admin.offer(s,admin_user,None,{'productId':product['id'],'batchCode':'BENCH-'+tag+'-'+str(n),
                'opensAt':(now()-timedelta(hours=1)).isoformat()+'Z','closesAt':(now()+timedelta(days=1)).isoformat()+'Z',
                'availableQty':'10000','status':'OPEN','prices':[{'groupId':g['id'],'unitPrice':str(10000+n*1000)} for g in groups]})
            offers.append(offer['id'])
        users=[];sessions=[]
        for n in range(args.clients):
            id=uid();raw=secrets.token_urlsafe(48);g=groups[n%len(groups)]
            users.append(dict(id=id,phone_e164='+98'+str(int(tag,16)).zfill(10)[-8:]+str(n).zfill(4),password_hash=admin_user['password_hash'],
                display_name=f'BENCH-{tag}-{n}',role='CUSTOMER',status='ACTIVE',group_id=g['id'],phone_verified_at=now(),
                security_version=1,version=1,created_at=now(),updated_at=now()))
            sessions.append(dict(id=uid(),user_id=id,token_hash=hashed(raw),security_version=1,created_at=now(),last_activity_at=now(),absolute_expires_at=now()+timedelta(hours=2)))
            actors.append((id,raw,g['id']))
        await s.execute(T['users'].insert(),users);await s.execute(T['sessions'].insert(),sessions);await flush_events(s)
    folder=ROOT/'evidence/comparison';folder.mkdir(parents=True,exist_ok=True)
    summaries=[];raw_rows=[]
    try:
        for repeat in range(args.repeats):
            # Alternate order to reduce warm-cache/order effects.
            modes=['wss','polling'] if repeat%2==0 else ['polling','wss']
            for mode in modes:
                result,observations=await scenario(args,mode,repeat,actors,offers,admin_user)
                summaries.append(result);raw_rows.extend(observations)
                print(json.dumps(result,ensure_ascii=False),flush=True)
        (folder/(tag+'.json')).write_text(json.dumps({'createdUtc':now().isoformat()+'Z','clients':args.clients,'warmupSeconds':args.warmup,
            'measurementSeconds':args.seconds,'updatesPerSecond':2,'pollIntervalSeconds':2,'repeats':args.repeats,'benchmarkOfferCount':args.offers,'runs':summaries,
            'validTiming':True,'timingGate':'producer timestamp >= measured phase start; warmup versions excluded',
            'byteScope':'UTF-8 JSON application payload only, no TLS/HTTP headers; bootstrap excluded after warmup',
            'latencyScope':'producer pre-transaction to observer parsing canonical offer version, same perf_counter clock; not browser pixel paint',
            'topology':'single Windows PC loopback; 50/50 two price groups'},ensure_ascii=False,indent=2),encoding='utf-8')
        with (folder/(tag+'-observations.csv')).open('w',encoding='utf-8',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=['mode','repeat','observer','offerId','version','latencyMs']);writer.writeheader();writer.writerows(raw_rows)
    finally:
        async with Session.begin() as s:
            await s.execute(T['offers'].update().where(T['offers'].c.id.in_(offers)).values(status='CLOSED',updated_at=now(),version=T['offers'].c.version+1))
            await s.execute(T['sessions'].update().where(T['sessions'].c.user_id.in_([a[0] for a in actors])).values(revoked_at=now()))
            await s.execute(T['users'].update().where(T['users'].c.id.in_([a[0] for a in actors])).values(status='DELETED'))
        await engine.dispose()

async def scenario(args,mode,repeat,actors,offers,admin_user):
    measured=False;measurement_start=float('inf');stop=asyncio.Event();markers={};expected={};observations=[];latencies=[];seen=set();models=[{} for _ in actors]
    counters={'requests':0,'messages':0,'bytes':0,'errors':0};connections=[];tasks=[];semaphore=asyncio.Semaphore(25)
    client=httpx.AsyncClient(base_url=args.url,verify=False,timeout=30,limits=httpx.Limits(max_connections=200,max_keepalive_connections=100))
    def consume(index,items):
        for o in items:
            models[index][o['id']]=str(o['version']);key=(o['id'],str(o['version']));observation=(index,*key)
            if measured and key in markers and markers[key]>=measurement_start and observation not in seen:
                seen.add(observation);latency=round((time.perf_counter()-markers[key])*1000,3);latencies.append(latency)
                observations.append({'mode':mode,'repeat':repeat+1,'observer':index,'offerId':o['id'],'version':o['version'],'latencyMs':latency})
    async def poll(index,actor):
        await asyncio.sleep(index/len(actors)*2)
        while not stop.is_set():
            start=time.perf_counter()
            try:
                r=await client.get('/api/v1/catalog/offers',headers={'Cookie':'ro_session='+actor[1]})
                if measured:counters['requests']+=1;counters['bytes']+=len(r.content)
                if r.status_code!=200:raise RuntimeError('HTTP_'+str(r.status_code))
                consume(index,r.json())
            except Exception:counters['errors']+=1
            await asyncio.sleep(max(0,2-(time.perf_counter()-start)))
    async def listen(index,ws):
        try:
            async for raw in ws:
                m=json.loads(raw)
                if measured:counters['messages']+=1;counters['bytes']+=len(raw.encode())
                if m['type']=='PING':await ws.send(json.dumps({'v':1,'type':'PONG'}))
                if m['type']=='EVENT' and m.get('eventType')=='CATALOG_CHANGED':consume(index,m['payload'].get('offers',[]))
        except Exception:
            if not stop.is_set():counters['errors']+=1
    async def establish(index,actor):
        async with semaphore:
            ws=await websockets.connect(args.url.replace('https:','wss:')+'/ws',origin=settings.app_origin,
                additional_headers={'Cookie':'ro_session='+actor[1]},ssl=ssl._create_unverified_context(),open_timeout=60,ping_interval=None)
            await ws.send(json.dumps({'v':1,'type':'HELLO','hasModel':False}));chunks=[]
            while True:
                m=json.loads(await ws.recv())
                if m['type']=='SNAPSHOT_CHUNK':chunks.append(m['data'])
                if m['type']=='SYNC_END':break
            consume(index,json.loads(''.join(chunks))['offers']);connections.append(ws);tasks.append(asyncio.create_task(listen(index,ws)))
    if mode=='wss':await asyncio.gather(*(establish(i,a) for i,a in enumerate(actors)))
    else:tasks=[asyncio.create_task(poll(i,a)) for i,a in enumerate(actors)]
    async def producer():
        n=0
        while not stop.is_set():
            start=time.perf_counter();id=offers[n%len(offers)];n+=1
            async with Session.begin() as s:
                offer=await one(s,'offers',T['offers'].c.id==id,lock=True)
                prices=(await s.execute(select(T['offer_prices']).where(T['offer_prices'].c.offer_id==id))).mappings().all()
                key=(id,str(offer['version']+1));markers[key]=time.perf_counter()
                result=await admin.offer(s,admin_user,id,{'expectedVersion':str(offer['version']),
                    'prices':[{'groupId':p['group_id'],'unitPrice':str(p['unit_price']+1),'expectedVersion':str(p['version'])} for p in prices]})
                await flush_events(s)
            expected[id]=str(result['version'])
            await asyncio.sleep(max(0,.5-(time.perf_counter()-start)))
    producer_task=asyncio.create_task(producer());await asyncio.sleep(args.warmup)
    measurement_start=time.perf_counter();measured=True;await asyncio.sleep(args.seconds);measured=False
    producer_task.cancel();await asyncio.gather(producer_task,return_exceptions=True)
    await asyncio.sleep(2.5)
    convergence=sum(all(int(model.get(id,0))>=int(v) for id,v in expected.items()) for model in models)
    stop.set()
    for t in tasks:t.cancel()
    await asyncio.gather(*(ws.close() for ws in connections),return_exceptions=True);await asyncio.gather(*tasks,return_exceptions=True);await client.aclose()
    return {'mode':mode,'repeat':repeat+1,'clients':len(actors),'seconds':args.seconds,**counters,
        'observedChanges':len(latencies),'p50Ms':percentile(latencies,.5),'p95Ms':percentile(latencies,.95),
        'convergedClientsAfterDrain':convergence},observations

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--clients',type=int,default=100);parser.add_argument('--seconds',type=int,default=60)
    parser.add_argument('--warmup',type=int,default=15);parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--url',default='https://localhost:3443')
    parser.add_argument('--offers',type=int,default=100)
    args=parser.parse_args();assert 1<=args.clients<=2000 and 5<=args.seconds<=600 and 1<=args.repeats<=3
    asyncio.run(main(args))
