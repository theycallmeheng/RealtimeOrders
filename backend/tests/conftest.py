import json
from pathlib import Path
from datetime import timedelta
import httpx
import pytest_asyncio
from app.db import engine, Session, reflect, T, uid, now, one

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
    yield result
    for c in result: await c.http.aclose()
    await engine.dispose()

@pytest_asyncio.fixture
async def sale(clients):
    admin=clients[0]; products=await admin.get('/admin/products'); product=products[0]
    result=await admin.post('/admin/offers',{'productId':product['id'],'batchCode':'TEST-'+uid()[:8],
        'opensAt':(now()-timedelta(hours=1)).isoformat()+'Z','closesAt':(now()+timedelta(days=1)).isoformat()+'Z',
        'availableQty':'10','status':'OPEN','prices':[{'groupId':id,'unitPrice':'100000'} for id in DATA['groups'].values()]})
    yield result
    async with Session.begin() as s:
        current=await one(s,'offers',T['offers'].c.id==result['id'])
    r=await admin.request('PATCH','/admin/offers/'+result['id'],{'expectedVersion':str(current['version']),'status':'CLOSED'})
    assert r.status_code==200,r.text

async def order_body(c,sale,quantity='1',other=None):
    offers=await c.get('/catalog/offers'); offer=next(o for o in offers if o['id']==sale['id'])
    addresses=await c.get('/me/addresses'); options=await c.get('/delivery/options')
    addr=addresses[0]; policy=next(p for p in options['policies'] if p['zone_id']==addr['zone_id'] and p['method']=='INDIVIDUAL')
    lines=[{'offerId':offer['id'],'quantity':quantity,'expectedPriceVersion':str(offer['price_version'])}]
    if other:
        o=next(o for o in offers if o['id']==other['id']); lines.append({'offerId':o['id'],'quantity':'2','expectedPriceVersion':str(o['price_version'])})
    return {'clientOrderId':uid(),'addressId':addr['id'],'deliveryMethod':'INDIVIDUAL','policyVersion':str(policy['version']),'items':lines}
