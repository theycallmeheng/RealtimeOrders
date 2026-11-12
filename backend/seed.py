"""Seed initial demo catalog/configuration once; never update an existing account DB."""
import asyncio
import json
import re
import secrets
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select, func, update
from app.db import T, Session, engine, reflect, now, uid, add, change
from app.marketplace import DEFAULT_SHOP
from app.auth import password_hash
from app.config import ROOT
from app.pricing import DEFAULT_RULES, menu_prices
from app.stock import movement

CATALOG = Path(__file__).with_name('seed_catalog.json')
DEMO_PICKUP_POINTS = (
    ('PTIT Hà Đông (mẫu)', '96A Trần Phú, phường Hà Đông, Hà Nội'),
    ('Đại học Kiến trúc Hà Nội (mẫu)', '129 Trần Phú, phường Hà Đông, Hà Nội'),
    ('Đại học Phenikaa (mẫu)', 'Đường Nguyễn Trác, phường Dương Nội, Hà Nội'),
    ('Đại học Khoa học Tự nhiên – ĐHQGHN (mẫu)', '334 Nguyễn Trãi, Thanh Xuân, Hà Nội'),
    ('Đại học Hà Nội (mẫu)', 'Km 9, Nguyễn Trãi, phường Đại Mỗ, Hà Nội'),
    ('Đại học Công nghệ Giao thông vận tải (mẫu)', '54 Triều Khúc, phường Thanh Liệt, Hà Nội'),
    ('FPT Polytechnic Hà Nội (mẫu)', '13 Phan Tây Nhạc, phường Xuân Phương, Hà Nội'),
    ('Keangnam Landmark 72 (mẫu)', 'Khu E6, đường Phạm Hùng, Hà Nội'),
    ('Đại học Thương mại (mẫu)', '79 Hồ Tùng Mậu, phường Từ Liêm, Hà Nội'),
)


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
            from app.shop import DEFAULT_PROFILE
            for key,value in [('shop_profile',DEFAULT_PROFILE),('vat_policy',{'rate':0})]:
                await add(s,'system_settings',setting_key=key,value_json=value,version=1,updated_by=accounts[0]['id'],updated_at=now())
            await change(s,'shops',DEFAULT_SHOP,name=DEFAULT_PROFILE['name'],profile_json=DEFAULT_PROFILE,updated_at=now())
            staff_accounts=[]
            for index,(name,role) in enumerate([('Người bán mẫu','SELLER'),('Người giao mẫu','SHIPPER')],5):
                id=uid();password=secrets.token_urlsafe(12)+'aA1';phone=f'+8490000000{index}'
                await add(s,'users',id=id,phone_e164=phone,password_hash=await password_hash(password),display_name=name,role=role,shop_id=DEFAULT_SHOP if role=='SELLER' else None,status='ACTIVE',group_id=groups['WORKER'],phone_verified_at=now(),security_version=1,version=1,created_at=now(),updated_at=now())
                staff_accounts.append({'id':id,'name':name,'role':role,'phone':phone,'password':password})
            await add(s,'system_settings',setting_key='warehouse',value_json={
                'latitude':'20.9809427','longitude':'105.7870861','placeId':'pin:20.9809427,105.7870861',
                'address':'96A Trần Phú, Học viện Công nghệ Bưu chính Viễn thông, Hà Đông, Hà Nội'},
                version=1,updated_by=accounts[0]['id'],updated_at=now())
            for code in groups:
                first,extra=(3000,4000) if code=='STUDENT' else (3500,5000)
                await add(s,'delivery_policies',id=uid(),group_id=groups[code],method='INDIVIDUAL',
                    minimum_subtotal=0,shipping_fee=0,active=True,version=1,
                    distance_enabled=True,pricing_mode='TIERED_KM',per_km_fee=first,included_km=10,
                    extra_km_fee=extra,max_distance_km=15,distance_rounding='EXACT',fee_rounding_step=1000)
            from app.menus import pickup_window
            pickup_start,pickup_end=pickup_window(now())
            point_ids=[]
            for name,address in DEMO_PICKUP_POINTS:
                point_id=uid()
                await add(s,'pickup_slots',id=point_id,name=name,address_line=address,
                          starts_at=pickup_start,ends_at=pickup_end,active=True,version=1)
                point_ids.append(point_id)
            for account in accounts[1:]:
                addressid=uid()
                await add(s,'addresses',id=addressid,user_id=account['id'],recipient_name=account['name'],phone_e164=account['phone'],
                    address_line='Số 17, đường Nguyễn Trãi, Hà Đông (địa chỉ mẫu)',version=1,created_at=now(),updated_at=now())
                await s.execute(update(T['users']).where(T['users'].c.id==account['id']).values(default_address_id=addressid))
            categories={};units={};products=[];max_sku=0
            # Fresh demo databases start with usable inventory and an auditable
            # opening receipt. Existing databases are left untouched above.
            opening_id=uid()
            opening_quantity=Decimal('10')
            opening_total=sum(opening_quantity*Decimal(str(item['cost'])) for item in catalog)
            seed_actor={'id':accounts[0]['id']}
            await add(s,'stock_receipts',id=opening_id,supplier_id=None,actor_id=seed_actor['id'],kind='OPENING',
                invoice_number='SEED-OPENING-STOCK',due_date=None,note='Tồn kho mẫu khi khởi tạo cơ sở dữ liệu',
                total=opening_total,confirmed_at=now())
            for item in catalog:
                category=item['category'];unit_code=item['unit_code']
                if category not in categories:
                    existing_category=await s.scalar(select(T['categories'].c.id).where(T['categories'].c.name==category).limit(1))
                    categories[category]=existing_category or uid()
                    if not existing_category:
                        await add(s,'categories',id=categories[category],name=category,active=True,version=1)
                if unit_code not in units:
                    units[unit_code]=uid();await add(s,'units',id=units[unit_code],code=unit_code,label=item['unit'])
                productid=uid();sku=item['sku'];match=re.fullmatch(r'SKU-(\d+)',sku)
                if match:max_sku=max(max_sku,int(match.group(1)))
                allowed=item.get('allowed_groups')
                allowed_ids=None if allowed is None else [groups[code] for code in allowed]
                standard=menu_prices(item['cost'],[{'id':groups['WORKER'],'code':'WORKER','active':True}])[0]['unitPrice']
                await add(s,'products',id=productid,category_id=categories[category],unit_id=units[unit_code],sku=sku,name=item['name'],
                    description=item['description'],quantity_step=item['quantity_step'],active=True,version=1,
                    default_cost_price=item['cost'],default_sale_price=standard,list_price=standard,allowed_group_ids=allowed_ids,created_at=now(),updated_at=now())
                await add(s,'product_stock',product_id=productid)
                line_total=opening_quantity*Decimal(str(item['cost']))
                await add(s,'stock_receipt_items',receipt_id=opening_id,product_id=productid,
                    quantity=opening_quantity,unit_cost=item['cost'],line_total=line_total)
                await movement(s,seed_actor,productid,opening_quantity,'OPENING',opening_id,
                    cost=Decimal(str(item['cost'])),reason='Tồn kho mẫu khi khởi tạo cơ sở dữ liệu')
                for position,url in enumerate(item.get('image_urls',[])):
                    await add(s,'product_images',product_id=productid,asset_id=None,source_url=url,position=position)
                products.append({'id':productid,'name':item['name'],'sku':sku})
            await s.execute(update(T['sku_sequences']).where(T['sku_sequences'].c.sequence_key=='product').values(next_value=max_sku+1))
            await add(s,'moderation_rules',id=uid(),phrase_normalized='từcấmmẫu',match_mode='TOKEN',active=True,version=1)
            for topic in ['admin:ops']+['catalog:'+id for id in groups.values()]+['user:'+a['id'] for a in accounts]:
                await add(s,'stream_heads',topic=topic,last_seq=0)
        target=Path(output_dir) if output_dir is not None else ROOT/'runtime'
        target.mkdir(parents=True,exist_ok=True)
        (target/'demo-accounts.local.json').write_text(json.dumps({'accounts':accounts,'staffAccounts':staff_accounts,'products':products,'groups':groups,'pickupSlotId':point_ids[0]},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Sample catalog ready: {len(products)} products. Credentials saved locally.')
        return True
    finally:
        await engine.dispose()

if __name__=='__main__':
    asyncio.run(seed())
