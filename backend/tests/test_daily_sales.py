"""Real MySQL/TCP acceptance, with explicitly synthetic route fixtures."""
import json
import sys
from datetime import timedelta,date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock,patch
import pytest
from sqlalchemy import select
from app.db import T,Session,one,change,uid,now,Fault
from app import menus,shipping,analytics
from conftest import order_body,quote_fixture
from test_integration import socket,sync_messages


@pytest.mark.parametrize('meters,fee',[(0,15000),(2999,15000),(3000,15000),(3001,18000),(3999,18000),(4000,18000),(4001,21000),(10000,36000)])
def test_route_fee_boundaries(meters,fee):
    p={'distance_enabled':True,'included_km':Decimal(3),'extra_km_fee':Decimal(3000),'max_distance_km':Decimal(10),'shipping_fee':Decimal(15000)}
    assert shipping.fee_for(p,meters)==fee
    with pytest.raises(Fault,match='ngoài phạm vi'): shipping.fee_for(p,10001)


def test_location_signature_expiry_and_vn_midnight():
    loc={'latitude':'20.98','longitude':'105.79','expires':(now()+timedelta(minutes=1)).timestamp()}
    assert shipping.verify_location(shipping.location_token(loc))==loc
    with pytest.raises(Fault):shipping.verify_location(shipping.location_token(loc)+'x')
    with pytest.raises(Fault):shipping.verify_location(shipping.location_token({**loc,'expires':0}))
    a,b=menus.bounds('2026-10-28');assert a.isoformat()=='2026-10-27T17:00:00' and b-a==timedelta(days=1)


async def test_goong_adapter_handles_distance_and_no_route():
    address={'latitude':'21','longitude':'105'};wh={'latitude':'20','longitude':'105'}
    fake={'routes':[{'legs':[{'distance':{'value':3101},'duration':{'value':720}}]}]}
    with patch.object(shipping,'goong',AsyncMock(return_value=fake)) as call:
        meters,seconds,_=await shipping.route(address,wh)
        assert (meters,seconds)==(3101,720);assert call.call_args.args[1]['vehicle']=='bike'
    with patch.object(shipping,'goong',AsyncMock(return_value={'routes':[]})):
        with pytest.raises(Fault):await shipping.route(address,wh)


async def test_map_key_missing_has_honest_error():
    with patch.object(shipping.settings,'goong_api_key',''):
        with pytest.raises(Fault) as err:await shipping.search('96A Trần Phú')
        assert err.value.code=='MAP_NOT_CONFIGURED'


@pytest.mark.parametrize('method,path',[('GET','/product-requests'),('POST','/product-requests'),('GET','/admin/product-requests'),
    ('POST','/product-requests/'+('0'*8+'-0000-0000-0000-'+'0'*12)+'/convert')])
async def test_request_feature_retired(clients,method,path):
    c=clients[0] if '/admin/' in path else clients[1]
    response=await c.request(method,path,{})
    assert response.status_code==410 and response.json()['error']['code']=='FEATURE_RETIRED'


async def test_menu_copy_zero_stock_unique_day_and_open_guard(clients,sale):
    admin=clients[0];target=date(2036,1,1)+timedelta(days=int(uid().replace('-','')[:4],16))
    copied=await admin.post('/admin/menus/'+sale['menu_id']+'/copy',{'saleDate':str(target)})
    assert copied['status']=='DRAFT' and all(Decimal(i['available_qty'])==0 for i in copied['items'])
    r=await admin.request('PATCH','/admin/menus/'+copied['id'],{'expectedVersion':copied['version'],'status':'OPEN'})
    assert r.status_code==400 and r.json()['error']['code']=='STOCK_REQUIRED'
    r=await admin.request('POST','/admin/menus',{'saleDate':str(target),'items':[]})
    assert r.status_code==409


async def test_product_audience_blocks_http_order_snapshot_and_stale_replay(clients,sale):
    admin,a,b=clients[:3];body=await order_body(b,sale)
    ws=await socket(b);messages=await sync_messages(ws);await ws.close()
    epoch=messages[-1]['datasetEpoch'];heads=messages[-1]['heads']
    product=next(p for p in await admin.get('/admin/products') if p['id']==sale['product_id'])
    updated=await admin.request('PATCH','/admin/products/'+product['id'],{'expectedVersion':product['version'],'allowedGroupIds':[a.user['group_id']]})
    assert updated.status_code==200,updated.text
    try:
        assert sale['id'] in [o['id'] for o in await a.get('/catalog/offers')]
        assert sale['id'] not in [o['id'] for o in await b.get('/catalog/offers')]
        assert (await b.request('POST','/orders',body)).status_code==409
        ws=await socket(b,hasModel=True,lastSeq=heads,datasetEpoch=epoch);messages=await sync_messages(ws);await ws.close()
        assert next(m for m in messages if m['type']=='SYNC_BEGIN')['mode']=='SNAPSHOT'
        snapshot=json.loads(''.join(m['data'] for m in messages if m['type']=='SNAPSHOT_CHUNK'))
        assert sale['id'] not in [o['id'] for o in snapshot['offers']]
        assert 'cost_price' not in json.dumps(snapshot) and 'cost_price_snapshot' not in json.dumps(snapshot)
    finally:
        current=next(p for p in await admin.get('/admin/products') if p['id']==product['id'])
        await admin.request('PATCH','/admin/products/'+product['id'],{'expectedVersion':current['version'],'allowedGroupIds':None})


async def test_menu_group_intersection_and_closed_day(clients,sale):
    admin,a,b=clients[:3];m=await admin.get('/admin/menus/'+sale['menu_id'])
    r=await admin.request('PATCH','/admin/menus/'+m['id'],{'expectedVersion':m['version'],'allowedGroupIds':[a.user['group_id']]})
    assert r.status_code==200,r.text
    try:
        assert sale['id'] not in [o['id'] for o in await b.get('/catalog/offers')]
        assert sale['id'] in [o['id'] for o in await a.get('/catalog/offers')]
    finally:
        m=await admin.get('/admin/menus/'+m['id']);await admin.request('PATCH','/admin/menus/'+m['id'],{'expectedVersion':m['version'],'allowedGroupIds':None})
    async with Session.begin() as s:
        m=await one(s,'daily_menus',T['daily_menus'].c.id==sale['menu_id'])
        await change(s,'daily_menus',m['id'],closes_at=now()-timedelta(seconds=1))
    try: assert sale['id'] not in [o['id'] for o in await a.get('/catalog/offers')]
    finally:
        async with Session.begin() as s:await change(s,'daily_menus',m['id'],closes_at=m['closes_at'])


@pytest.mark.parametrize('change_kind',['expire','cart','address','policy','warehouse'])
async def test_delivery_quote_binding(clients,sale,change_kind):
    c=clients[1];body=await order_body(c,sale)
    if change_kind=='cart':body['items'][0]['quantity']='2'
    async with Session.begin() as s:
        q=await one(s,'delivery_quotes',T['delivery_quotes'].c.id==body['deliveryQuoteId'])
        if change_kind=='expire':await change(s,'delivery_quotes',q['id'],expires_at=now()-timedelta(seconds=1))
        elif change_kind=='address':await change(s,'delivery_quotes',q['id'],address_version=q['address_version']+1)
        elif change_kind=='policy':await change(s,'delivery_quotes',q['id'],policy_version=q['policy_version']+1)
        elif change_kind=='warehouse':await change(s,'delivery_quotes',q['id'],warehouse_version=q['warehouse_version']+1)
    r=await c.request('POST','/orders',body)
    assert r.status_code==409 and r.json()['error']['code']=='REQUOTE_REQUIRED'


async def test_cost_is_immutable_private_and_negative_profit_is_real(clients,sale):
    admin,c=clients[:2]
    async with Session.begin() as s:await change(s,'offers',sale['id'],cost_price=Decimal(120000))
    order=await c.post('/orders',await order_body(c,sale,'1.5'))
    order=await admin.post('/admin/orders/'+order['id']+'/approve',{'expectedVersion':order['version']})
    assert order['items'][0]['cost_price_snapshot']=='120000'
    async with Session.begin() as s:await change(s,'offers',sale['id'],cost_price=Decimal(20000))
    for target in ('PREPARING','SHIPPING','DELIVERED'):
        order=await admin.post('/admin/orders/'+order['id']+'/transition',{'expectedVersion':order['version'],'status':target})
    assert 'cost_price_snapshot' not in (await c.get('/orders/'+order['id']))['items'][0]
    # Isolate a business date without altering any primary/live data.
    day=date(2050,1,1)+timedelta(days=int(uid().replace('-','')[:4],16))
    async with Session.begin() as s:await change(s,'orders',order['id'],delivered_at=menus.bounds(day)[0]+timedelta(hours=1))
    result=await admin.get('/admin/reports/daily?date='+str(day))
    assert result['selected']['merchandise']=='150000' and result['selected']['cost']=='180000'
    assert result['selected']['grossProfit']=='-30000' and result['changes']['merchandise']['percent'] is None
    async with Session.begin() as s:await change(s,'order_items',order['items'][0]['id'],cost_price_snapshot=None)
    result=await admin.get('/admin/reports/daily?date='+str(day))
    assert result['selected']['grossProfit'] is None and result['selected']['missingCostLines']==1


async def test_cleanup_preserves_recent_orders_and_is_repeatable(clients):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
    from cleanup_sales import preview,apply,fingerprint,preserved
    async with Session() as s:
        await s.begin()
        try:
            cutoff=date(2026,10,28);before=await preserved(s,cutoff);manifest=await preview(s,cutoff)
            result=await apply(s,cutoff,fingerprint(manifest))
            assert fingerprint(before)==result['preservedHash']
            second=await preview(s,cutoff)
            assert not second['orderIds'] and not second['offerIds']
            again=await apply(s,cutoff,fingerprint(second))
            assert again['ordersDeleted']==again['offersDeleted']==0
        finally:await s.rollback()
