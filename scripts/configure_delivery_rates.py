"""Configure approved demo delivery rates. Preview unless --apply is specified."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.db import Session,T,reflect,rows,one,now,public,engine
from app import admin
from app.events import flush_events

async def main(apply):
    await reflect()
    try:
        async with Session.begin() as s:
            groups={g['id']:g['code'] for g in await rows(s,'customer_groups',T['customer_groups'].c.active==True)}
            policies=await rows(s,'delivery_policies',limit=1000)
            candidates={}
            for policy in sorted(policies,key=lambda p:(not p['active'],not p['distance_enabled'],-p['version'],p['id'])):
                if policy['method']=='INDIVIDUAL':
                    candidates.setdefault(policy['group_id'],policy)
            plan=[]
            for gid,code in groups.items():
                first,extra=(3000,4000) if code=='STUDENT' else (3500,5000)
                policy=candidates.get(gid,{'id':None})
                values=dict(groupId=gid,active=True,distanceEnabled=True,pricingMode='TIERED_KM',
                            shippingFee='0',perKmFee=str(first),includedKm='10',extraKmFee=str(extra),
                            maxDistanceKm='15',distanceRounding='EXACT',feeRoundingStep='1000')
                plan.append((policy,values,code))
            if not {'STUDENT','WORKER'}<=set(groups.values()):
                raise RuntimeError('Missing delivery policy; no rates changed')
            print(json.dumps([{'group':code,**v} for _,v,code in plan],ensure_ascii=True))
            if not apply:
                print('Preview only. Pass --apply to save approved rates.');return
            backup=ROOT/'runtime/backups'/('delivery-policies-before-approved-rates-'+now().strftime('%Y%m%dT%H%M%S%fZ')+'.json')
            backup.parent.mkdir(parents=True,exist_ok=True)
            backup.write_text(json.dumps(public(policies),ensure_ascii=False,indent=2),encoding='utf-8')
            user=await one(s,'users',T['users'].c.role=='ADMIN')
            for p,values,_ in plan:
                await admin.configuration(s,user,'delivery_policies',p['id'],{**values,'expectedVersion':str(p.get('version',''))})
            await flush_events(s)
            print(f'Applied {len(plan)} policies atomically; previous rates backed up.')
    finally: await engine.dispose()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true')
    asyncio.run(main(parser.parse_args().apply))
