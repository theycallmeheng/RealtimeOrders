"""Register the previously confirmed public warehouse as a searchable address."""
import asyncio
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import geocoding,shipping
from app.db import Session,T,reflect,one,engine
from app.events import flush_events

async def main():
    await reflect()
    try:
        async with Session.begin() as s:
            wh=await shipping.warehouse(s)
            if not wh['configured']:
                raise RuntimeError('Confirm warehouse coordinates in the admin UI first')
            if abs(float(wh['latitude'])-20.9809427)>.001 or abs(float(wh['longitude'])-105.7870861)>.001:
                raise RuntimeError('Warehouse is not at the confirmed PTIT point; register the correct address through the admin UI')
            label='96A Trần Phú, Học viện Công nghệ Bưu chính Viễn thông, Hà Đông, Hà Nội'
            existing=await one(s,'verified_locations',T['verified_locations'].c.label==label,required=False)
            if existing:
                print('Confirmed warehouse address already registered');return
            user=await one(s,'users',T['users'].c.role=='ADMIN')
            point=shipping.pin_location({'latitude':wh['latitude'],'longitude':wh['longitude'],'address':label})
            await geocoding.save_verified(s,user,None,{'label':label,'houseNumber':'96A','street':'Trần Phú',
                'aliases':['96A Trần Phú','96A Trần Phú Hà Đông Hà Nội','PTIT Hà Đông',
                           'Học viện Công nghệ Bưu chính Viễn thông Hà Đông'],
                'locationToken':point['locationToken']})
            await flush_events(s)
            print('Registered public warehouse using its previously confirmed coordinates; no customer addresses imported')
    finally: await engine.dispose()

if __name__=='__main__': asyncio.run(main())
