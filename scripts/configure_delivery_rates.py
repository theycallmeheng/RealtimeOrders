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
            plan=[]
            for p in policies:
                code=groups.get(p['group_id'])
                if p['method']=='INDIVIDUAL' and code is not None:
                    first,extra=(3000,4000) if code=='STUDENT' else (3500,5000)
                    values=dict(active=True,distanceEnabled=True,pricingMode='TIERED_KM',shippingFee='0',
                                perKmFee=str(first),includedKm='10',extraKmFee=str(extra),maxDistanceKm='15',
                                distanceRounding='EXACT',feeRoundingStep='1000')
                elif p['method']=='COLLECTIVE' and code=='STUDENT':
                    values=dict(active=True,distanceEnabled=False,pricingMode='BASE_PLUS_EXTRA',shippingFee='0',
                                perKmFee='0',includedKm='0',extraKmFee='0',maxDistanceKm=None,
                                distanceRounding='EXACT',feeRoundingStep='1000')
                else: continue
                plan.append((p,values,code))
            existing={(p['group_id'],p['zone_id'],p['method']) for p in policies}
            zones=await rows(s,'delivery_zones',T['delivery_zones'].c.active==True)
            for gid,code in groups.items():
                for zone in zones:
                    if (gid,zone['id'],'INDIVIDUAL') in existing: continue
                    first,extra=(3000,4000) if code=='STUDENT' else (3500,5000)
                    p={'id':None,'group_id':gid,'zone_id':zone['id'],'method':'INDIVIDUAL'}
                    values=dict(groupId=gid,zoneId=zone['id'],method='INDIVIDUAL',minimumSubtotal='0',
                                active=True,distanceEnabled=True,pricingMode='TIERED_KM',shippingFee='0',
                                perKmFee=str(first),includedKm='10',extraKmFee=str(extra),maxDistanceKm='15',
                                distanceRounding='EXACT',feeRoundingStep='1000')
                    plan.append((p,values,code))
            required={('STUDENT','INDIVIDUAL'),('WORKER','INDIVIDUAL'),('STUDENT','COLLECTIVE')}
            if not required<={(code,p['method']) for p,_,code in plan}:
                raise RuntimeError('Missing delivery policy; no rates changed')
            print(json.dumps([{'group':code,'method':p['method'],**v} for p,v,code in plan],ensure_ascii=True))
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
