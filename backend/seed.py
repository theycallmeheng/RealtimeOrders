"""Seed initial demo catalog/configuration once; never update an existing account DB."""
import asyncio
import json
import re
import secrets
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select, func, update
from app.db import T, Session, engine, reflect, now, uid, add
from app.auth import password_hash
from app.config import ROOT
from app.pricing import DEFAULT_RULES, menu_prices

CATALOG = Path(__file__).with_name('seed_catalog.json')


async def seed(output_dir=None):
    await reflect()
    try:
        catalog=json.loads(CATALOG.read_text(encoding='utf-8'))
        async with Session.begin() as s:
            existing=(await s.execute(select(func.count()).select_from(T['users']))).scalar_one()
            if existing:
                print('Database already has users; sample seed left unchanged.')
                return False
            groups={}
            for code,name in [('STUDENT','Sinh viên'),('WORKER','Người đi làm'),('VIP','Khách hàng thân thiết')]:
                groups[code]=uid();await add(s,'customer_groups',id=groups[code],code=code,name=name,active=True,version=1)
            accounts=[]
            for n,(name,role,group) in enumerate([('Quản trị mẫu','ADMIN','WORKER'),('Nguyễn An','CUSTOMER','STUDENT'),
                                                    ('Trần Bình','CUSTOMER','WORKER'),('Lê Chi','CUSTOMER','VIP')]):
                id=uid();password=secrets.token_urlsafe(12)+'aA1';phone=f'+8490000000{n+1}'
                await add(s,'users',id=id,phone_e164=phone,password_hash=await password_hash(password),display_name=name,role=role,
                          status='ACTIVE',group_id=groups[group],phone_verified_at=now(),security_version=1,version=1,created_at=now(),updated_at=now())
                accounts.append({'id':id,'name':name,'role':role,'group':group,'phone':phone,'password':password})
            await add(s,'system_settings',setting_key='price_rules',value_json=DEFAULT_RULES,version=1,updated_by=accounts[0]['id'],updated_at=now())
            await add(s,'system_settings',setting_key='warehouse',value_json={
                'latitude':'20.9809427','longitude':'105.7870861','placeId':'pin:20.9809427,105.7870861',
                'address':'96A Trần Phú, Học viện Công nghệ Bưu chính Viễn thông, Hà Đông, Hà Nội'},
                version=1,updated_by=accounts[0]['id'],updated_at=now())
            zone=uid();await add(s,'delivery_zones',id=zone,code='HADONG',name='Hà Đông — khu giao mẫu',description='Dữ liệu phục vụ demo',active=True,version=1)
            for code in groups:
                first,extra=(3000,4000) if code=='STUDENT' else (3500,5000)
                await add(s,'delivery_policies',id=uid(),group_id=groups[code],zone_id=zone,method='INDIVIDUAL',
                    minimum_subtotal=0,shipping_fee=0,active=True,version=1,
                    distance_enabled=True,pricing_mode='TIERED_KM',per_km_fee=first,included_km=10,
                    extra_km_fee=extra,max_distance_km=15,distance_rounding='EXACT',fee_rounding_step=1000)
            await add(s,'delivery_policies',id=uid(),group_id=groups['STUDENT'],zone_id=zone,method='COLLECTIVE',
                minimum_subtotal=0,shipping_fee=0,active=True,version=1,distance_enabled=False,
                pricing_mode='BASE_PLUS_EXTRA',per_km_fee=0,included_km=0,extra_km_fee=0,
                max_distance_km=None,distance_rounding='EXACT',fee_rounding_step=1000)
            slot=uid();await add(s,'pickup_slots',id=slot,zone_id=zone,name='Cổng trường — 17:00 đến 18:00',
                address_line='Điểm giao mẫu tại cổng trường',starts_at=now()+timedelta(hours=1),ends_at=now()+timedelta(days=30),active=True,version=1)
            for account in accounts[1:]:
                addressid=uid()
                await add(s,'addresses',id=addressid,user_id=account['id'],zone_id=zone,recipient_name=account['name'],phone_e164=account['phone'],
                    address_line='Số 17, đường Nguyễn Trãi, Hà Đông (địa chỉ mẫu)',version=1,created_at=now(),updated_at=now())
                await s.execute(update(T['users']).where(T['users'].c.id==account['id']).values(default_address_id=addressid))
            categories={};units={};products=[];max_sku=0
            for item in catalog:
                category=item['category'];unit_code=item['unit_code']
                if category not in categories:
                    categories[category]=uid();await add(s,'categories',id=categories[category],name=category,active=True,version=1)
                if unit_code not in units:
                    units[unit_code]=uid();await add(s,'units',id=units[unit_code],code=unit_code,label=item['unit'])
                productid=uid();sku=item['sku'];match=re.fullmatch(r'SKU-(\d+)',sku)
                if match:max_sku=max(max_sku,int(match.group(1)))
                allowed=item.get('allowed_groups')
                allowed_ids=None if allowed is None else [groups[code] for code in allowed]
                standard=menu_prices(item['cost'],[{'id':groups['WORKER'],'code':'WORKER','active':True}])[0]['unitPrice']
                await add(s,'products',id=productid,category_id=categories[category],unit_id=units[unit_code],sku=sku,name=item['name'],
                    description=item['description'],quantity_step=item['quantity_step'],active=True,version=1,
                    default_cost_price=item['cost'],default_sale_price=standard,allowed_group_ids=allowed_ids,created_at=now(),updated_at=now())
                for position,url in enumerate(item.get('image_urls',[])):
                    await add(s,'product_images',product_id=productid,asset_id=None,source_url=url,position=position)
                products.append({'id':productid,'name':item['name'],'sku':sku})
            await s.execute(update(T['sku_sequences']).where(T['sku_sequences'].c.sequence_key=='product').values(next_value=max_sku+1))
            await add(s,'moderation_rules',id=uid(),phrase_normalized='từcấmmẫu',match_mode='TOKEN',active=True,version=1)
            for topic in ['admin:ops']+['catalog:'+id for id in groups.values()]+['user:'+a['id'] for a in accounts]:
                await add(s,'stream_heads',topic=topic,last_seq=0)
        target=Path(output_dir) if output_dir is not None else ROOT/'runtime'
        target.mkdir(parents=True,exist_ok=True)
        (target/'demo-accounts.local.json').write_text(json.dumps({'accounts':accounts,'products':products,'groups':groups,'zoneId':zone,'pickupSlotId':slot},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Sample catalog ready: {len(products)} products. Credentials saved locally.')
        return True
    finally:
        await engine.dispose()

if __name__=='__main__':
    asyncio.run(seed())
