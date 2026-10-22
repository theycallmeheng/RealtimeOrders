"""Explicit, repeatable sample data. Random local credentials; no default password."""
import asyncio
import json
import secrets
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select, func
from app.db import T, Session, engine, reflect, now, uid, add, one
from app.auth import password_hash
from app.config import ROOT

async def seed():
    await reflect()
    async with Session.begin() as s:
        existing=(await s.execute(select(func.count()).select_from(T['users']))).scalar_one()
        if existing:
            print('Database already has users; sample seed left unchanged.'); return
        groups={}
        for code,name in [('STUDENT','Sinh viên'),('WORKER','Người đi làm')]:
            groups[code]=uid(); await add(s,'customer_groups',id=groups[code],code=code,name=name,active=True,version=1)
        accounts=[]
        for n,(name,role,group) in enumerate([('Quản trị mẫu','ADMIN','WORKER'),('Nguyễn An','CUSTOMER','STUDENT'),
                                             ('Trần Bình','CUSTOMER','WORKER'),('Lê Chi','CUSTOMER','STUDENT')]):
            id=uid(); password=secrets.token_urlsafe(12)+'aA1'; phone=f'+8490000000{n+1}'
            await add(s,'users',id=id,phone_e164=phone,password_hash=await password_hash(password),display_name=name,role=role,
                      status='ACTIVE',group_id=groups[group],phone_verified_at=now(),security_version=1,version=1,created_at=now(),updated_at=now())
            accounts.append({'id':id,'name':name,'role':role,'group':group,'phone':phone,'password':password})
        zone=uid(); await add(s,'delivery_zones',id=zone,code='HADONG',name='Hà Đông — khu giao mẫu',description='Dữ liệu phục vụ demo',active=True,version=1)
        for code in groups:
            for method in (['INDIVIDUAL','COLLECTIVE'] if code=='STUDENT' else ['INDIVIDUAL']):
                await add(s,'delivery_policies',id=uid(),group_id=groups[code],zone_id=zone,method=method,
                          minimum_subtotal=50000 if code=='STUDENT' and method=='INDIVIDUAL' else 0,
                          shipping_fee=0 if method=='COLLECTIVE' else 15000 if code=='STUDENT' else 20000,active=True,version=1)
        slot=uid(); await add(s,'pickup_slots',id=slot,zone_id=zone,name='Cổng trường — 17:00 đến 18:00',address_line='Điểm giao mẫu tại cổng trường',
                              starts_at=now()+timedelta(hours=1),ends_at=now()+timedelta(days=30),active=True,version=1)
        for account in accounts[1:]:
            addressid=uid()
            await add(s,'addresses',id=addressid,user_id=account['id'],zone_id=zone,recipient_name=account['name'],phone_e164=account['phone'],
                      address_line='Số 17, đường Nguyễn Trãi, Hà Đông (địa chỉ mẫu)',version=1,created_at=now(),updated_at=now())
            await s.execute(T['users'].update().where(T['users'].c.id==account['id']).values(default_address_id=addressid))
        category=uid(); await add(s,'categories',id=category,name='Thực phẩm trong ngày',active=True,version=1)
        units={}
        for code,label in [('KG','kg'),('BOX','hộp'),('BAG','túi')]:
            units[code]=uid(); await add(s,'units',id=units[code],code=code,label=label)
        products=[]
        for n,(name,unit,step,stock,student,worker,description) in enumerate([
            ('Cam sành','KG','.100','120','28000','32000','Cam tươi, bán theo cân. Dữ liệu mẫu.'),
            ('Trứng gà 10 quả','BOX','1','80','30000','35000','Hộp 10 quả, nhận hàng trong ngày.'),
            ('Gạo thơm 5 kg','BAG','1','50','115000','125000','Túi đóng sẵn 5 kg.'),
            ('Khoai lang','KG','.100','100','18000','22000','Có thể mua theo bước 0,1 kg.'),
            ('Sữa chua 4 hộp','BOX','1','60','24000','28000','Bảo quản mát, kiểm tra khi nhận.')]):
            productid=uid(); offerid=uid()
            await add(s,'products',id=productid,category_id=category,unit_id=units[unit],sku=f'DEMO-{n+1:03}',name=name,
                      description=description,quantity_step=step,active=True,version=1,created_at=now(),updated_at=now())
            await add(s,'offers',id=offerid,product_id=productid,sale_date=now().date(),batch_code='DEMO',status='OPEN',available_qty=stock,
                      opens_at=now()-timedelta(days=1),closes_at=now()+timedelta(days=30),version=1,created_at=now(),updated_at=now())
            for code,amount in [('STUDENT',student),('WORKER',worker)]:
                await add(s,'offer_prices',offer_id=offerid,group_id=groups[code],unit_price=amount,version=1)
            await add(s,'inventory_movements',id=uid(),offer_id=offerid,actor_id=accounts[0]['id'],kind='OPENING',reference_id=offerid,
                      quantity_delta=stock,balance_after=stock,reason='Dữ liệu mẫu',created_at=now())
            products.append({'id':productid,'offerId':offerid,'name':name})
        await add(s,'moderation_rules',id=uid(),phrase_normalized='từcấmmẫu',match_mode='TOKEN',active=True,version=1)
        for topic in ['admin:ops']+['catalog:'+id for id in groups.values()]+['user:'+a['id'] for a in accounts]:
            await add(s,'stream_heads',topic=topic,last_seq=0)
    path=ROOT/'runtime'; path.mkdir(exist_ok=True)
    (path/'demo-accounts.local.json').write_text(json.dumps({'accounts':accounts,'products':products,'groups':groups,'zoneId':zone,'pickupSlotId':slot},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Sample data ready. Random credentials: runtime/demo-accounts.local.json (local, ignored).')
    await engine.dispose()

asyncio.run(seed())
