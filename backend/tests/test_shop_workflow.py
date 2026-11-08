"""Real isolated MySQL/TCP workflows; provider money is explicitly simulated."""
import asyncio
import hashlib
import hmac
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, func
from app import payments, auth, menus
from app.config import settings
from app.db import T, Session, one, change, now, uid, Fault
from app.events import flush_events
from app.realtime import topics_for
from app.marketplace import shop_topic
from conftest import Client, ORIGIN, DATA, order_body


@pytest_asyncio.fixture(scope='module')
async def roles(clients):
    result=[]
    for role in ('SELLER','SHIPPER','SHIPPER'):
        phone='+849'+str(int(uid().replace('-','')[:8],16)).zfill(10)[-8:]
        password='IsolatedStaff123!'
        await clients[0].post('/admin/staff',{'name':'Workflow '+role,'phone':phone,'password':password,'role':role})
        http=httpx.AsyncClient(base_url=ORIGIN,verify=False,timeout=30)
        r=await http.post('/api/v1/auth/login',headers={'Origin':ORIGIN},json={'identifier':phone,'password':password})
        assert r.status_code==200
        result.append(Client(http,r.json()))
    yield result
    for c in result:await c.http.aclose()


async def approved(clients,sale,customer=None,method='COD'):
    customer=customer or clients[1]
    body=await order_body(customer,sale)
    if method=='PAYOS':
        from app.main import app
        with patch.multiple(settings,payos_client_id='fixture',payos_api_key='fixture',payos_checksum_key='fixture-secret'):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,cookies=customer.http.cookies) as http:
                r=await http.post('/api/v1/orders',headers={'Origin':ORIGIN,'X-CSRF-Token':customer.session['csrfToken'],'Idempotency-Key':uid()},json={**body,'paymentMethod':'PAYOS'})
                assert r.status_code==200,r.text
                order=r.json()
    else:order=await customer.post('/orders',body)
    return await clients[0].post('/admin/orders/'+order['id']+'/approve',{'expectedVersion':order['version']})


async def assign(actor,order,courier):
    return await actor.post('/shop/orders/'+order['id']+'/assign',{'expectedVersion':order['version'],'courierId':courier.user['id']})


def signed(req,amount=None,reference=None):
    data={'orderCode':req['order_code'],'amount':int(amount if amount is not None else req['amount']),
          'reference':reference or uid(),'paymentLinkId':req.get('provider_link_id') or 'fixture-link','currency':'VND','code':'00','desc':'success'}
    return {'code':'00','success':True,'data':data,'signature':payments.signature(data)}


async def request_fixture(order):
    async with Session.begin() as s:
        from app.db import add
        await add(s,'payment_requests',id=uid(),order_id=order['id'],amount=order['total'],expires_at=now()+timedelta(minutes=15),state='PENDING',provider_link_id=uid(),created_at=now(),updated_at=now())
        return await one(s,'payment_requests',T['payment_requests'].c.order_id==order['id'])


async def receipt(body):
    async with Session.begin() as s:
        result=await payments.webhook(s,body);await flush_events(s)
        return result


async def test_roles_http_and_topics_are_separate(clients,roles):
    seller,courier,_=roles
    assert (await seller.request('GET','/admin/orders')).status_code==403
    assert isinstance(await seller.get('/shop/products'),list)
    assert (await seller.request('GET','/shop/config/moderation-rules')).status_code==403
    assert (await seller.request('GET','/admin/vat')).status_code==403
    assert (await clients[1].request('GET','/shop/orders')).status_code==403
    assert (await courier.request('GET','/catalog/offers')).status_code==403
    assert (await courier.request('GET','/shop/finance')).status_code==403
    assert await topics_for(None,seller.user)==['user:'+seller.user['id'],shop_topic(seller.user['shop_id']),'shops:refresh']
    assert await topics_for(None,courier.user)==['user:'+courier.user['id'],'courier:'+courier.user['id']]
    assert (await seller.request('POST','/admin/staff',{})).status_code==403


async def test_vat_snapshot_and_requote(clients,sale):
    admin,c=clients[:2];old=await admin.get('/admin/vat')
    try:
        await admin.request('PATCH','/admin/vat',{'expectedVersion':old['version'],'rate':'8.25'})
        body=await order_body(c,sale)
        bad=await c.request('POST','/orders',body)
        assert bad.status_code==409 and bad.json()['error']['code']=='REQUOTE_REQUIRED'
        config=await c.get('/checkout/config')
        o=await c.post('/orders',{**body,'vatVersion':config['vatVersion']})
        assert Decimal(o['vat_amount'])==payments.tax(Decimal(o['merchandise_total']),'8.25')
        assert Decimal(o['total'])==Decimal(o['merchandise_total'])+Decimal(o['vat_amount'])+Decimal(o['shipping_fee'])
        policy=await admin.get('/admin/vat')
        await admin.request('PATCH','/admin/vat',{'expectedVersion':policy['version'],'rate':'10'})
        unchanged=await c.get('/orders/'+o['id'])
        assert unchanged['vat_rate']==o['vat_rate'] and unchanged['total']==o['total']
    finally:
        current=await admin.get('/admin/vat')
        await admin.request('PATCH','/admin/vat',{'expectedVersion':current['version'],'rate':old['value']['rate']})


async def test_cod_assignment_collection_remittance_and_reviews(clients,sale,roles):
    seller,courier,other=roles;o=await approved(clients,sale)
    o=await seller.post('/shop/orders/'+o['id']+'/transition',{'expectedVersion':o['version'],'status':'PREPARING'})
    bad=await seller.request('POST','/shop/orders/'+o['id']+'/transition',{'expectedVersion':o['version'],'status':'SHIPPING'})
    assert bad.status_code==409 and bad.json()['error']['code']=='COURIER_REQUIRED'
    o=await assign(seller,o,courier)
    assert (await other.request('GET','/orders/'+o['id'])).status_code==403
    assert all(x['id']!=o['id'] for x in await other.get('/courier/orders'))
    assert any(x['id']==o['id'] for x in await courier.get('/courier/orders'))
    assert all('cost_price_snapshot' not in i for x in await courier.get('/courier/orders') for i in x['items'])
    o=await seller.post('/shop/orders/'+o['id']+'/transition',{'expectedVersion':o['version'],'status':'SHIPPING'})
    bad=await courier.request('POST','/courier/orders/'+o['id']+'/transition',{'expectedVersion':o['version'],'status':'DELIVERED','codAmount':'1'})
    assert bad.status_code==409
    key=uid();body={'expectedVersion':o['version'],'status':'DELIVERED','codAmount':o['total']}
    delivered=await courier.post('/courier/orders/'+o['id']+'/transition',body,key)
    assert delivered['payment_status']=='PAID' and delivered['status']=='DELIVERED'
    assert (await courier.post('/courier/orders/'+o['id']+'/transition',body,key))['id']==o['id']
    async with Session() as s:
        entries=await s.execute(select(T['money_entries']).where(T['money_entries'].c.order_id==o['id']))
        entry=entries.mappings().one();assert entry['method']=='COD' and entry['amount']==Decimal(o['total'])
    assert (await courier.request('POST','/shop/money/'+entry['id']+'/remit',{'received':True})).status_code==403
    assert (await seller.request('POST','/shop/money/'+entry['id']+'/remit',{'received':True})).status_code==403
    await clients[0].post('/shop/money/'+entry['id']+'/remit',{'received':True})
    await clients[0].post('/shop/money/'+entry['id']+'/remit',{'received':True})
    review=await clients[1].post('/reviews',{'orderId':o['id'],'target':'PRODUCT','itemId':o['items'][0]['id'],'rating':5,'comment':'Tốt'})
    assert (await clients[1].request('POST','/reviews',{'orderId':o['id'],'itemId':o['items'][0]['id'],'rating':4})).status_code==409
    assert (await clients[2].request('POST','/reviews',{'orderId':o['id'],'itemId':o['items'][0]['id'],'rating':5})).status_code==404
    await clients[1].post('/reviews',{'orderId':o['id'],'target':'COURIER','rating':4})
    public=await clients[1].get('/reviews/product/'+sale['product_id'])
    assert public['count']>=1 and all('customer_id' not in r for r in public['reviews'])
    await clients[0].post('/admin/reviews/'+review['id']+'/hide',{'reason':'Kiểm thử ẩn nội dung'})
    assert all(r['id']!=review['id'] for r in (await clients[1].get('/reviews/product/'+sale['product_id']))['reviews'])


async def test_collective_pickup_notifies_only_order_owner(clients,sale,roles):
    seller,courier,_=roles;c=clients[1];options=await c.get('/delivery/options')
    policy=next(p for p in options['policies'] if p['method']=='COLLECTIVE');slot=options['pickupSlots'][0]
    body=await order_body(c,sale)
    body.update(deliveryMethod='COLLECTIVE',policyVersion=policy['version'],pickupSlotId=slot['id'],pickupSlotVersion=slot['version'])
    o=await c.post('/orders',body);o=await clients[0].post('/admin/orders/'+o['id']+'/approve',{'expectedVersion':o['version']})
    o=await assign(seller,o,courier)
    for status in ('PREPARING','READY_FOR_PICKUP'):
        o=await seller.post('/shop/orders/'+o['id']+'/transition',{'expectedVersion':o['version'],'status':status})
    notices=await c.get('/notifications')
    assert any(n['kind']=='PICKUP_READY' and n['payload']['id']==o['id'] for n in notices)
    assert all(n['payload'].get('id')!=o['id'] for n in await clients[2].get('/notifications'))
    o=await courier.post('/courier/orders/'+o['id']+'/transition',{'expectedVersion':o['version'],'status':'DELIVERED','codAmount':o['total']})
    assert o['status']=='DELIVERED' and o['shipping_fee']=='0'


async def test_failed_delivery_requires_return_before_stock_restore(clients,sale,roles):
    seller,courier,_=roles;o=await assign(seller,await approved(clients,sale),courier)
    for target in ('PREPARING','SHIPPING'):o=await seller.post('/shop/orders/'+o['id']+'/transition',{'expectedVersion':o['version'],'status':target})
    o=await courier.post('/courier/orders/'+o['id']+'/delivery-failed',{'expectedVersion':o['version'],'reason':'Không liên hệ được'})
    async with Session() as s:assert (await one(s,'offers',T['offers'].c.id==sale['id']))['available_qty']==9
    assert (await seller.request('POST','/shop/orders/'+o['id']+'/confirm-return',{'expectedVersion':o['version']})).status_code==409
    o=await seller.post('/shop/orders/'+o['id']+'/confirm-return',{'expectedVersion':o['version'],'received':True,'reason':'Đã nhận đủ'})
    assert o['status']=='CANCELLED'
    async with Session() as s:assert (await one(s,'offers',T['offers'].c.id==sale['id']))['available_qty']==10


def test_tax_rounds_half_up_and_signature_matches_documented_canonical_order():
    assert payments.tax(Decimal(125),'10')==13
    data={'returnUrl':'https://example.invalid/orders','orderCode':123,'description':'RO123','cancelUrl':'https://example.invalid/orders','amount':1000}
    canonical='amount=1000&cancelUrl=https://example.invalid/orders&description=RO123&orderCode=123&returnUrl=https://example.invalid/orders'
    with patch.object(settings,'payos_checksum_key','fixture-secret'):
        assert payments.signature(data)==hmac.new(b'fixture-secret',canonical.encode(),hashlib.sha256).hexdigest()
        assert not payments.verified(data,'bad')


async def test_payos_disabled_without_credentials(clients,sale):
    c=clients[1];body=await order_body(c,sale)
    assert not (await c.get('/checkout/config'))['payosAvailable']
    r=await c.request('POST','/orders',{**body,'paymentMethod':'PAYOS'})
    assert r.status_code==503 and 'key' not in r.text.lower()


async def test_payos_link_retry_reuses_provider_code_no_network_under_transaction(clients,sale):
    o=await approved(clients,sale,method='PAYOS');calls=[]
    async def fake(method,path,payload=None,**kwargs):
        calls.append((method,path,payload))
        if method=='GET':return None
        return {'orderCode':payload['orderCode'],'amount':payload['amount'],'paymentLinkId':uid(),'checkoutUrl':'https://pay.payos.vn/web/fixture'}
    with patch.multiple(settings,payos_client_id='fixture',payos_api_key='fixture',payos_checksum_key='fixture-secret'),patch.object(payments,'provider',side_effect=fake):
        first=await payments.link(clients[1].user,o['id']);second=await payments.link(clients[1].user,o['id'])
    assert first['id']==second['id'] and [c[0] for c in calls]==['GET','POST']
    assert len(calls[-1][2]['description'])<=9 and calls[-1][2]['amount']==int(o['total'])


async def test_signed_payment_duplicate_race_and_paid_cancel_refund(clients,sale):
    o=await approved(clients,sale,method='PAYOS');req=await request_fixture(o)
    with patch.multiple(settings,payos_client_id='fixture',payos_api_key='fixture',payos_checksum_key='fixture-secret'):
        body=signed(req)
        with pytest.raises(Fault):await receipt({**body,'signature':'bad'})
        await asyncio.gather(receipt(body),receipt(body))
    paid=await clients[1].get('/orders/'+o['id']);assert paid['payment_status']=='PAID'
    async with Session() as s:
        assert (await s.execute(select(func.count()).select_from(T['money_entries']).where(T['money_entries'].c.order_id==o['id']))).scalar_one()==1
    requested=await clients[1].post('/orders/'+o['id']+'/cancellation-requests',{'expectedVersion':paid['version'],'reason':'Đổi kế hoạch'})
    cancelled=await clients[0].post('/admin/orders/'+o['id']+'/decide-cancel',{'expectedVersion':requested['version'],'accept':True})
    assert cancelled['payment_status']=='REFUND_PENDING'
    async with Session() as s:refund=await one(s,'refund_requests',T['refund_requests'].c.order_id==o['id'])
    body={'amount':str(refund['amount']),'reference':'fixture-'+uid(),'note':'Simulated bank refund'}
    await clients[0].post('/admin/refunds/'+refund['id']+'/confirm',body)
    await clients[0].post('/admin/refunds/'+refund['id']+'/confirm',body)
    refunded=await clients[1].get('/orders/'+o['id'])
    assert refunded['payment_status']=='REFUNDED' and refunded['payment']['remaining']=='0'


async def test_payment_expiry_late_webhook_and_partial_not_fulfillable(clients,sale):
    o=await approved(clients,sale,method='PAYOS');req=await request_fixture(o)
    with patch.multiple(settings,payos_client_id='fixture',payos_api_key='fixture',payos_checksum_key='fixture-secret'):
        await receipt(signed(req,amount=1))
        current=await clients[1].get('/orders/'+o['id']);assert current['payment_status']=='UNPAID'
        bad=await clients[0].request('POST','/admin/orders/'+o['id']+'/transition',{'expectedVersion':current['version'],'status':'PREPARING'})
        assert bad.status_code==409 and bad.json()['error']['code']=='PAYMENT_REQUIRED'
        async with Session.begin() as s:
            await change(s,'orders',o['id'],payment_deadline=now()-timedelta(seconds=1))
            await payments.expire_order(s,o);await payments.expire_order(s,o);await flush_events(s)
        assert (await clients[1].get('/orders/'+o['id']))['status']=='CANCELLED'
        await receipt(signed(req,amount=int(o['total'])-1))
    final=await clients[1].get('/orders/'+o['id']);assert final['status']=='CANCELLED' and final['payment_status']=='REFUND_PENDING'
    async with Session() as s:
        refund=await one(s,'refund_requests',T['refund_requests'].c.order_id==o['id'])
        assert refund['amount']==Decimal(o['total'])
        assert (await one(s,'offers',T['offers'].c.id==sale['id']))['available_qty']==10


async def test_feed_group_privacy_and_post_uses_live_prices(clients,sale,roles):
    seller=roles[0];menu=await seller.get('/shop/menus/'+sale['menu_id'])
    menu=await seller.request('PATCH','/shop/menus/'+menu['id'],{'expectedVersion':menu['version'],'postTitle':'Bài thử nghiệm','postBody':'Hàng hôm nay','receivingNote':'Đến đúng giờ','audienceMode':'MENU','allowedGroupIds':[clients[1].user['group_id']]})
    assert menu.status_code==200,menu.text
    try:
        yes=await clients[1].get('/feed');no=await clients[2].get('/feed')
        assert any(p['id']==sale['menu_id'] and p['post_title']=='Bài thử nghiệm' for p in yes['posts'])
        assert all(p['id']!=sale['menu_id'] for p in no['posts'])
        assert all('cost_price' not in o for p in yes['posts'] for o in p['offers'])
    finally:
        fresh=await seller.get('/shop/menus/'+sale['menu_id'])
        await seller.request('PATCH','/shop/menus/'+fresh['id'],{'expectedVersion':fresh['version'],'allowedGroupIds':None})


async def test_old_orders_keep_unknown_payment_state(clients):
    async with Session() as s:
        old=await one(s,'orders',T['orders'].c.payment_method=='LEGACY',required=False)
    if not old:pytest.skip('No historical order in this isolated database')
    result=await clients[0].get('/orders/'+old['id'])
    assert result['payment_status']=='LEGACY' and not result['payment']['tracked']
    assert Decimal(result['vat_amount'])==0


async def test_recover_lost_link_response_uses_existing_provider_id(clients,sale):
    o=await approved(clients,sale,method='PAYOS');calls=[];link_id=uid().replace('-','')
    async def fake(method,path,payload=None,**kwargs):
        calls.append((method,path))
        if len(calls)==1:return None
        if method=='POST':raise Fault('PAYMENT_UNAVAILABLE','Simulated lost response',503)
        return {'id':link_id,'orderCode':int(path[1:]),'amount':int(o['total']),'amountPaid':0,'status':'PENDING'}
    with patch.multiple(settings,payos_client_id='fixture',payos_api_key='fixture',payos_checksum_key='fixture-secret'),patch.object(payments,'provider',side_effect=fake):
        result=await payments.link(clients[1].user,o['id'])
    assert result['checkout_url']=='https://pay.payos.vn/web/'+link_id
    assert calls[0]==calls[2] and len(calls)==3


async def test_webhook_route_requires_signature_not_browser_origin(clients,sale):
    from app.main import app
    o=await approved(clients,sale,method='PAYOS');req=await request_fixture(o)
    with patch.multiple(settings,payos_client_id='fixture',payos_api_key='fixture',payos_checksum_key='fixture-secret'):
        body=signed(req)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            bad=await client.post('/api/v1/payments/payos/webhook',json={**body,'signature':'wrong'})
            assert bad.status_code==400
            good=await client.post('/api/v1/payments/payos/webhook',json=body)
            assert good.status_code==200
            duplicate=await client.post('/api/v1/payments/payos/webhook',json=body)
            assert duplicate.status_code==200
    paid=await clients[1].get('/orders/'+o['id']);assert paid['payment_status']=='PAID'
