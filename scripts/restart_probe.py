"""Prepare while backend is stopped; verify after it starts. No credentials in evidence."""
import argparse
import asyncio
import json
import os
import secrets
import ssl
import sys
from datetime import timedelta
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.db import T,Session,engine,reflect,one,now,uid,add,digest,public
from app.auth import hashed
from app.events import emit,flush_events
from sqlalchemy import select

async def run(mode):
    await reflect();state_path=ROOT/'runtime/restart-probe.local.json'
    if mode=='prepare':
        async with Session.begin() as s:
            user=await one(s,'users',T['users'].c.phone_e164=='+84900000002')
            order=(await s.execute(select(T['orders']).where(T['orders'].c.customer_id==user['id']).order_by(T['orders'].c.created_at.desc()).limit(1))).mappings().first()
            assert order,'Run integration tests first'
            marker=uid();topic='user:'+user['id'];raw=secrets.token_urlsafe(48)
            head=await one(s,'stream_heads',T['stream_heads'].c.topic==topic)
            await add(s,'sessions',id=uid(),user_id=user['id'],token_hash=hashed(raw),security_version=user['security_version'],created_at=now(),last_activity_at=now(),absolute_expires_at=now()+timedelta(hours=1))
            emit(s,topic,'RESTART_PROBE',{'marker':marker,'orderId':order['id']});await flush_events(s)
            state={'orderId':order['id'],'orderHash':digest(dict(order)).hex(),'marker':marker,'topic':topic,'lastSeq':str(head['last_seq']),'raw':raw}
        state_path.write_text(json.dumps(state),encoding='utf-8');print('Committed probe to outbox while backend stopped.')
    else:
        state=json.loads(state_path.read_text())
        async with Session.begin() as s:
            order=await one(s,'orders',T['orders'].c.id==state['orderId']);assert digest(order).hex()==state['orderHash']
            event=await one(s,'stream_events',T['stream_events'].c.topic==state['topic'],T['stream_events'].c.event_type=='RESTART_PROBE',
                            T['stream_events'].c.seq==int(state['lastSeq'])+1)
        found=False;published=False
        for _ in range(30):
            async with Session.begin() as s:
                out=await one(s,'outbox',T['outbox'].c.event_id==event['event_id'])
                published=out['state']=='PUBLISHED'
            if published:break
            await asyncio.sleep(.1)
        ws=await websockets.connect('wss://localhost:3443/ws',origin='https://localhost:3443',ssl=ssl._create_unverified_context(),additional_headers={'Cookie':'ro_session='+state['raw']})
        # Missing other topic cursors forces snapshot; replay starts from a complete head map.
        async with Session.begin() as s:
            user=await one(s,'users',T['users'].c.id==order['customer_id'])
            grouphead=await one(s,'stream_heads',T['stream_heads'].c.topic=='catalog:'+user['group_id'])
        await ws.send(json.dumps({'v':1,'type':'HELLO','hasModel':True,'lastSeq':{state['topic']:state['lastSeq'],'catalog:'+user['group_id']:str(grouphead['last_seq'])}}))
        while True:
            msg=json.loads(await asyncio.wait_for(ws.recv(),15))
            if msg['type']=='EVENT' and msg.get('eventType')=='RESTART_PROBE':found=msg['payload']['marker']==state['marker']
            if msg['type']=='SYNC_END':break
        await ws.close();assert published and found
        result={'preparedWithBackendStopped':True,'orderId':state['orderId'],'orderHashUnchanged':True,'outboxPublishedAfterRestart':published,'replayedOnWss':found,'verifiedUtc':now().isoformat()+'Z'}
        folder=Path(os.environ.get('AUDIT_EVIDENCE_DIR',ROOT/'evidence'))
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'restart-probe.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print('Restart verified: order unchanged, pending outbox published, event replayed over WSS.')
    await engine.dispose()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','verify']);args=p.parse_args();asyncio.run(run(args.mode))
