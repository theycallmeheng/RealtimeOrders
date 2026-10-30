import json
from pathlib import Path
from datetime import timedelta
import httpx
import pytest_asyncio
from app.db import engine, Session, reflect, T, uid, now, one,add,change,public

ORIGIN='https://localhost:3443'
DATA=json.loads((Path(__file__).resolve().parents[2]/'runtime/demo-accounts.local.json').read_text(encoding='utf-8'))

class Client:
    def __init__(self,client,session): self.http,self.session=client,session
    @property
    def user(self): return self.session['user']
    async def request(self,method,path,body=None,key=None,headers=None):
        h={'Origin':ORIGIN,'X-CSRF-Token':self.session['csrfToken']}
        if method!='GET': h['Idempotency-Key']=key or uid()
        h.update(headers or {})
        return await self.http.request(method,'/api/v1'+path,json=body,headers=h)
    async def get(self,path):
        r=await self.request('GET',path); assert r.status_code==200,r.text; return r.json()
    async def post(self,path,body,key=None):
        r=await self.request('POST',path,body,key); assert r.status_code==200,r.text; return r.json()

@pytest_asyncio.fixture(scope='session')
async def clients():
    await reflect(); result=[]
    for a in DATA['accounts']:
        http=httpx.AsyncClient(base_url=ORIGIN,verify=False,timeout=30)
        r=await http.post('/api/v1/auth/login',headers={'Origin':ORIGIN},json={'identifier':a['phone'],'password':a['password']})
        assert r.status_code==200,r.text
        result.append(Client(http,r.json()))
    # Reset only artifacts from earlier runs inside the audit database.
    async with Session.begin() as db:
        from sqlalchemy import update,select
        test_products=select(T['products'].c.id).where(
            T['products'].c.name.like('Audit item %')|T['products'].c.name.like('Other atomic %'))
        await db.execute(update(T['offers']).where(T['offers'].c.product_id.in_(test_products)).values(menu_id=None,archived_at=now(),status='CLOSED'))
    # Test-only route fixtures, never a fabricated production map provider.
    async with Session.begin() as db:
        from sqlalchemy import update
        for policy in (await db.execute(T['delivery_policies'].select())).mappings():
            if policy['method']=='INDIVIDUAL':
                await db.execute(update(T['delivery_policies']).where(T['delivery_policies'].c.id==policy['id']).values(distance_enabled=True,included_km=3,extra_km_fee=3000,max_distance_km=30))
        wh=await one(db,'system_settings',T['system_settings'].c.setting_key=='warehouse',required=False)
        if not wh: await add(db,'system_settings',setting_key='warehouse',value_json={'address':'Test warehouse (synthetic)','latitude':'20.98','longitude':'105.79','placeId':'test'},version=1,updated_by=result[0].user['id'],updated_at=now())
    from app.menus import today
    products=await result[0].get('/admin/products')
    menus=await result[0].get('/admin/menus')
    menu=next((m for m in menus if m['sale_date']==str(today())),None)
    if not menu:
        await result[0].post('/admin/menus',{'saleDate':str(today()),'status':'OPEN','items':[
            {'productId':p['id'],'availableQty':'100','costPrice':'10000','prices':[{'groupId':g,'unitPrice':'100000'} for g in DATA['groups'].values()]} for p in products[:5]]})
    yield result
    for c in result: await c.http.aclose()
    await engine.dispose()

@pytest_asyncio.fixture
async def sale(clients):
    admin=clients[0]; products=await admin.get('/admin/products'); template=products[0]
    product=await admin.post('/admin/products',{'name':'Audit item '+uid()[:8],'categoryId':template['category_id'],
        'unitId':template['unit_id'],'quantityStep':'.100','defaultCostPrice':'60000','defaultSalePrice':'100000'})
    result=await admin.post('/admin/offers',{'productId':product['id'],'batchCode':'TEST-'+uid()[:8],
        'opensAt':(now()-timedelta(hours=1)).isoformat()+'Z','closesAt':(now()+timedelta(days=1)).isoformat()+'Z',
        'availableQty':'10','costPrice':'60000','status':'OPEN','prices':[{'groupId':id,'unitPrice':'100000'} for id in DATA['groups'].values()]})
    yield result
    async with Session.begin() as s:
        current=await one(s,'offers',T['offers'].c.id==result['id'])
    r=await admin.request('PATCH','/admin/offers/'+result['id'],{'expectedVersion':str(current['version']),'status':'CLOSED'})
    assert r.status_code==200,r.text
    async with Session.begin() as s:
        await change(s,'offers',result['id'],menu_id=None,archived_at=now())

async def order_body(c,sale,quantity='1',other=None):
    offers=await c.get('/catalog/offers'); offer=next(o for o in offers if o['id']==sale['id'])
    addresses=await c.get('/me/addresses'); options=await c.get('/delivery/options')
    addr=addresses[0]; policy=next(p for p in options['policies'] if p['zone_id']==addr['zone_id'] and p['method']=='INDIVIDUAL')
    lines=[{'offerId':offer['id'],'quantity':quantity,'expectedPriceVersion':str(offer['price_version'])}]
    if other:
        o=next(o for o in offers if o['id']==other['id']); lines.append({'offerId':o['id'],'quantity':'2','expectedPriceVersion':str(o['price_version'])})
    body={'clientOrderId':uid(),'addressId':addr['id'],'deliveryMethod':'INDIVIDUAL','policyVersion':str(policy['version']),'items':lines}

    body['deliveryQuoteId']=await quote_fixture(c,body)
    return body

async def quote_fixture(c,body):
    """Persist a synthetic route result to exercise checkout bindings over real TCP."""
    from app.shipping import warehouse,record_quote,cart_hash
    from sqlalchemy import update
    async with Session.begin() as s:
        addr=await one(s,'addresses',T['addresses'].c.id==body['addressId'])
        await change(s,'addresses',addr['id'],latitude='20.99',longitude='105.80')
        addr=await one(s,'addresses',T['addresses'].c.id==addr['id'])
        p=await one(s,'delivery_policies',T['delivery_policies'].c.group_id==c.user['group_id'],T['delivery_policies'].c.zone_id==addr['zone_id'],T['delivery_policies'].c.method=='INDIVIDUAL')
        q=await record_quote(s,c.user,(addr,p,await warehouse(s),cart_hash(body['items'])),(3000,600,{'testOnly':True}))
        return q['id']
