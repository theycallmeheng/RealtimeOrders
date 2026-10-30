import asyncio
import io
import json
import ssl
from datetime import timedelta
from decimal import Decimal
import httpx
import pytest
import websockets
from PIL import Image
from sqlalchemy import select, func
from app.db import Session,T,one,change,uid,now
from conftest import ORIGIN,DATA,order_body,Client

async def test_tls_health(clients):
    r=await clients[0].http.get('/api/health'); assert r.status_code==200 and r.json()['demo']

async def test_unauthorized_and_admin_boundary(clients):
    async with httpx.AsyncClient(base_url=ORIGIN,verify=False) as h:
        assert (await h.get('/api/v1/orders')).status_code==401
    assert (await clients[1].request('GET','/admin/users')).status_code==403

async def test_csrf_and_origin(clients):
    c=clients[1]
    assert (await c.request('POST','/auth/activity',{},headers={'X-CSRF-Token':'wrong'})).status_code==403
    assert (await c.request('POST','/auth/activity',{},headers={'Origin':'https://evil.invalid'})).status_code==403

async def test_bad_login(clients):
    r=await clients[0].http.post('/api/v1/auth/login',headers={'Origin':ORIGIN},json={'identifier':DATA['accounts'][0]['phone'],'password':'incorrect-password'})
    assert r.status_code==401

async def test_registration_otp_unicode_reuse(clients):
    async with httpx.AsyncClient(base_url=ORIGIN,verify=False,headers={'Origin':ORIGIN}) as h:
        phone='+84'+str(int(uid().replace('-','')[:12],16))[:10]
        r=await h.post('/api/v1/auth/registration/otp',json={'phone':phone});assert r.status_code==200,r.text
        c=r.json();v=await h.post('/api/v1/auth/registration/verify',json={'challengeId':c['challengeId'],'code':c['demoCode']});assert v.status_code==200,v.text
        payload={'ticket':v.json()['ticket'],'displayName':'Nguyễn Ánh — tiếng Việt','password':'Test-Password-2026!'}
        r=await h.post('/api/v1/auth/register',json=payload);assert r.status_code==200,r.text
        assert r.json()['user']['display_name']=='Nguyễn Ánh — tiếng Việt'
        assert (await h.post('/api/v1/auth/register',json=payload)).status_code==400
        assert (await h.post('/api/v1/auth/registration/otp',json={'phone':phone})).status_code==409

async def test_otp_wrong_attempts_are_persisted(clients):
    async with httpx.AsyncClient(base_url=ORIGIN,verify=False,headers={'Origin':ORIGIN}) as h:
        c=(await h.post('/api/v1/auth/registration/otp',json={'phone':'+849'+str(int(uid().replace('-','')[:8],16))[:8]})).json()
        wrong='000000' if c['demoCode']!='000000' else '999999'
        for _ in range(5):
            r=await h.post('/api/v1/auth/registration/verify',json={'challengeId':c['challengeId'],'code':wrong});assert r.status_code==400
        r=await h.post('/api/v1/auth/registration/verify',json={'challengeId':c['challengeId'],'code':c['demoCode']});assert r.json()['error']['code']=='OTP_EXPIRED'
        async with Session.begin() as s:
            row=await one(s,'auth_challenges',T['auth_challenges'].c.id==c['challengeId']);assert row['attempts']==5

async def test_email_verification(clients):
    c=clients[2];email='test-'+uid()[:8]+'@example.invalid'
    challenge=await c.post('/auth/email/challenge',{'email':email})
    await c.post('/auth/email/verify',{'challengeId':challenge['challengeId'],'code':challenge['demoCode']})
    session=await c.get('/auth/session');assert session['user']['email_normalized']==email
    async with httpx.AsyncClient(base_url=ORIGIN,verify=False) as h:
        r=await h.post('/api/v1/auth/login',headers={'Origin':ORIGIN},json={'identifier':email,'password':DATA['accounts'][2]['password']});assert r.status_code==200

async def test_address_limit_concurrently(clients):
    c=clients[3]; existing=await c.get('/me/addresses')
    payload={'zoneId':DATA['zoneId'],'recipientName':'Khách thử','phone':c.user['phone_e164'],'addressLine':'Địa chỉ mẫu để kiểm tra đồng thời'}
    results=await asyncio.gather(*[c.request('POST','/me/addresses',payload) for _ in range(6)])
    assert sum(r.status_code==200 for r in results)==3-len(existing)
    assert len(await c.get('/me/addresses'))==3
    assert all(r.status_code in (200,409) for r in results)

async def test_address_ownership(clients):
    admin,a,b,_=clients;addr=(await a.get('/me/addresses'))[0]
    r=await b.request('PATCH','/me/addresses/'+addr['id'],{'expectedVersion':str(addr['version']),'makeDefault':True});assert r.status_code==404

async def test_group_prices_are_private(clients,sale):
    from sqlalchemy import update
    async with Session.begin() as s:
        for c,amount in ((clients[1],90000),(clients[2],100000)):
            await s.execute(update(T['offer_prices']).where(T['offer_prices'].c.offer_id==sale['id'],T['offer_prices'].c.group_id==c.user['group_id']).values(unit_price=amount))
    a=next(o for o in await clients[1].get('/catalog/offers') if o['id']==sale['id'])
    b=next(o for o in await clients[2].get('/catalog/offers') if o['id']==sale['id'])
    assert a['unit_price']=='90000' and b['unit_price']=='100000'
    assert 'prices' not in a and 'cost_price' not in a

async def test_pending_does_not_deduct_and_deduplicates(clients,sale):
    c=clients[1];body=await order_body(c,sale);key=uid()
    one_order=await c.post('/orders',body,key);same=await c.post('/orders',body,key)
    assert one_order['id']==same['id'];assert one_order['status']=='PENDING'
    async with Session.begin() as s:
        offer=await one(s,'offers',T['offers'].c.id==sale['id']);assert offer['available_qty']==10
    changed={**body,'note':'different'};r=await c.request('POST','/orders',changed,key);assert r.status_code==409
    # Permanent clientOrderId uniqueness survives use of a fresh transport key.
    assert (await c.post('/orders',body,uid()))['id']==one_order['id']

async def test_price_change_requires_requote(clients,sale):
    a,c=clients[:2];body=await order_body(c,sale)
    await a.request('PATCH','/admin/offers/'+sale['id'],{'expectedVersion':'1','prices':[{'groupId':c.user['group_id'],'unitPrice':'120000','expectedVersion':'1'}]})
    r=await c.request('POST','/orders',body);assert r.status_code==409 and r.json()['error']['code']=='REQUOTE_REQUIRED'

async def test_invalid_quantity_step(clients,sale):
    c=clients[1];body=await order_body(c,sale,'0.001')
    r=await c.request('POST','/orders',body);assert r.status_code==400

async def test_concurrent_approval_never_oversells(clients,sale):
    admin,a,b,_=clients
    orders=await asyncio.gather(a.post('/orders',await order_body(a,sale,'7')),b.post('/orders',await order_body(b,sale,'7')))
    results=await asyncio.gather(*[admin.request('POST','/admin/orders/'+o['id']+'/approve',{'expectedVersion':'1'}) for o in orders])
    assert sorted(r.status_code for r in results)==[200,409]
    async with Session.begin() as s:
        offer=await one(s,'offers',T['offers'].c.id==sale['id']);assert offer['available_qty']==3
        count=(await s.execute(select(func.count()).select_from(T['inventory_movements']).where(T['inventory_movements'].c.offer_id==sale['id'],T['inventory_movements'].c.kind=='APPROVE'))).scalar_one();assert count==1

async def test_multi_item_approval_is_atomic(clients,sale):
    admin,c=clients[:2]
    template=next(p for p in await admin.get('/admin/products') if p['id']==sale['product_id'])
    product=await admin.post('/admin/products',{'name':'Other atomic '+uid()[:8],'categoryId':template['category_id'],'unitId':template['unit_id'],'quantityStep':'.100','defaultCostPrice':'60000'})
    other=await admin.post('/admin/offers',{'productId':product['id'],'batchCode':'TEST-'+uid()[:8],
        'opensAt':(now()-timedelta(hours=1)).isoformat()+'Z','closesAt':(now()+timedelta(days=1)).isoformat()+'Z',
        'availableQty':'3','status':'OPEN','prices':[{'groupId':id,'unitPrice':'100000'} for id in DATA['groups'].values()]})
    o=await c.post('/orders',await order_body(c,sale,'2',other))
    await admin.post('/admin/inventory-adjustments',{'offerId':other['id'],'expectedVersion':'1','delta':'-2','reason':'Kiểm thử thiếu một dòng'})
    r=await admin.request('POST','/admin/orders/'+o['id']+'/approve',{'expectedVersion':'1'});assert r.status_code==409
    async with Session.begin() as s:
        assert (await one(s,'offers',T['offers'].c.id==sale['id']))['available_qty']==10
        assert (await one(s,'orders',T['orders'].c.id==o['id']))['status']=='PENDING'

async def test_cancellation_restores_exactly_once(clients,sale):
    a,c=clients[:2];o=await c.post('/orders',await order_body(c,sale,'2'))
    approved=await a.post('/admin/orders/'+o['id']+'/approve',{'expectedVersion':'1'})
    pending=await c.post('/orders/'+o['id']+'/cancellation-requests',{'expectedVersion':str(approved['version']),'reason':'Đổi kế hoạch nhận hàng'})
    key=uid();payload={'expectedVersion':str(pending['version']),'accept':True,'reason':'Chấp thuận'}
    cancelled=await a.post('/admin/orders/'+o['id']+'/decide-cancel',payload,key)
    again=await a.post('/admin/orders/'+o['id']+'/decide-cancel',payload,key)
    assert cancelled['id']==again['id'] and cancelled['status']=='CANCELLED'
    async with Session.begin() as s:
        assert (await one(s,'offers',T['offers'].c.id==sale['id']))['available_qty']==10
        count=(await s.execute(select(func.count()).select_from(T['inventory_movements']).where(T['inventory_movements'].c.order_id==o['id'],T['inventory_movements'].c.kind=='CANCEL_RESTORE'))).scalar_one();assert count==1

async def test_shipping_blocked_by_open_cancellation(clients,sale):
    a,c=clients[:2];o=await c.post('/orders',await order_body(c,sale));o=await a.post('/admin/orders/'+o['id']+'/approve',{'expectedVersion':'1'})
    o=await a.post('/admin/orders/'+o['id']+'/transition',{'expectedVersion':str(o['version']),'status':'PREPARING'})
    o=await c.post('/orders/'+o['id']+'/cancellation-requests',{'expectedVersion':str(o['version']),'reason':'Cần thay đổi'})
    r=await a.request('POST','/admin/orders/'+o['id']+'/transition',{'expectedVersion':str(o['version']),'status':'SHIPPING'})
    assert r.status_code==409 and r.json()['error']['code']=='CANCELLATION_OPEN'

async def test_status_versions_and_revenue(clients,sale):
    a,c=clients[:2];o=await c.post('/orders',await order_body(c,sale));o=await a.post('/admin/orders/'+o['id']+'/approve',{'expectedVersion':'1'})
    assert (await a.request('POST','/admin/orders/'+o['id']+'/transition',{'expectedVersion':'1','status':'PREPARING'})).status_code==409
    for target in ('PREPARING','SHIPPING','DELIVERED'):
        o=await a.post('/admin/orders/'+o['id']+'/transition',{'expectedVersion':str(o['version']),'status':target})
    report=await a.get('/admin/reports?start='+str(now().date())+'T00:00:00Z&end='+str((now()+timedelta(days=1)).date())+'T00:00:00Z')
    assert sum(int(r['merchandise']) for r in report['daily'])>=100000
    assert (await c.request('POST','/orders/'+o['id']+'/cancellation-requests',{'expectedVersion':str(o['version']),'reason':'Sau giao'})).status_code==409

async def test_order_privacy(clients,sale):
    o=await clients[1].post('/orders',await order_body(clients[1],sale))
    assert (await clients[2].request('GET','/orders/'+o['id'])).status_code==403

async def test_chat_moderation_dedup_and_privacy(clients):
    c=clients[1];conv=await c.get('/conversations/me');body={'clientMessageId':uid(),'text':'Xin hỏi từcấmmẫu cảm ơn','assetIds':[]}
    m=await c.post('/conversations/'+conv['id']+'/messages',body);m2=await c.post('/conversations/'+conv['id']+'/messages',body)
    assert m['id']==m2['id'] and 'từcấmmẫu' not in m['text_sanitized'] and '*' in m['text_sanitized']
    assert (await clients[2].request('GET','/conversations/'+conv['id']+'/messages')).status_code==403
    violations=await clients[0].get('/admin/moderation/violations');assert any(v['reference_id']==m['id'] for v in violations)

async def test_media_validation_and_chat_access(clients):
    c=clients[1];headers={'Origin':ORIGIN,'X-CSRF-Token':c.session['csrfToken']}
    bad=await c.http.post('/api/v1/media',headers=headers,data={'purpose':'CHAT'},files={'file':('fake.png',b'not an image','image/png')});assert bad.status_code==400,bad.text
    image=io.BytesIO();Image.new('RGB',(24,24),'teal').save(image,'PNG')
    r=await c.http.post('/api/v1/media',headers=headers,data={'purpose':'CHAT'},files={'file':('test.png',image.getvalue(),'image/png')});assert r.status_code==200,r.text
    id=r.json()['id'];assert (await clients[2].request('GET','/media/'+id)).status_code==403
    conv=await c.get('/conversations/me');await c.post('/conversations/'+conv['id']+'/messages',{'clientMessageId':uid(),'text':'Ảnh mẫu','assetIds':[id]})
    assert (await clients[0].request('GET','/media/'+id)).status_code==200


async def socket(c,**hello):
    cookie='; '.join(k+'='+v for k,v in c.http.cookies.items())
    ctx=ssl._create_unverified_context()
    ws=await websockets.connect('wss://localhost:3443/ws',origin=ORIGIN,additional_headers={'Cookie':cookie},ssl=ctx)
    await ws.send(json.dumps({'v':1,'type':'HELLO','hasModel':False,**hello}));return ws

async def sync_messages(ws):
    data=[]
    while True:
        m=json.loads(await asyncio.wait_for(ws.recv(),15));data.append(m)
        if m['type']=='PING':await ws.send(json.dumps({'v':1,'type':'PONG'}))
        if m['type']=='SYNC_END':return data

async def test_wss_snapshot_private_topics_and_replay(clients,sale):
    c=clients[1];ws=await socket(c)
    data=await sync_messages(ws);heads=data[-1]['heads'];welcome=next(m for m in data if m['type']=='WELCOME')
    assert 'admin:ops' not in welcome['topics']
    model=json.loads(''.join(m['data'] for m in data if m['type']=='SNAPSHOT_CHUNK'))
    assert all(o['customer_id']==c.user['id'] for o in model['orders'])
    await ws.close();await c.post('/orders',await order_body(c,sale))
    ws=await socket(c,hasModel=True,lastSeq=heads,datasetEpoch=data[-1]['datasetEpoch']);data=await sync_messages(ws);await ws.close()
    assert next(m for m in data if m['type']=='SYNC_BEGIN')['mode']=='REPLAY'
    assert any(m.get('eventType')=='ORDER_CHANGED' for m in data)

async def test_wss_wrong_origin_and_version(clients):
    cookie='; '.join(k+'='+v for k,v in clients[1].http.cookies.items())
    with pytest.raises(Exception):
        await websockets.connect('wss://localhost:3443/ws',origin='https://evil.invalid',additional_headers={'Cookie':cookie},ssl=ssl._create_unverified_context())
    ws=await socket(clients[1],v=99);m=json.loads(await ws.recv());assert m['type']=='ERROR' and m['code']=='PROTOCOL_VERSION';await ws.close()

async def test_oversized_json(clients):
    r=await clients[1].request('POST','/product-requests',{'note':'x'*70000});assert r.status_code==413

async def test_notifications_ownership(clients):
    c=clients[1];data=await c.get('/notifications');assert data
    assert (await clients[2].request('POST','/notifications/'+data[0]['id']+'/read',{})).status_code==404
    await c.post('/notifications/'+data[0]['id']+'/read',{})

async def test_z_session_revocation_and_idle(clients):
    a,c=clients[0],clients[3]
    user=next(u for u in await a.get('/admin/users') if u['id']==c.user['id'])
    r=await a.request('PATCH','/admin/users/'+user['id'],{'expectedVersion':str(user['version']),'status':'LOCKED'});assert r.status_code==200,r.text
    assert (await c.request('GET','/orders')).status_code==401
    r=await a.request('PATCH','/admin/users/'+user['id'],{'expectedVersion':str(r.json()['version']),'status':'ACTIVE'});assert r.status_code==200
    # Reopening an account does not resurrect revoked sessions.
    assert (await c.request('GET','/orders')).status_code==401
