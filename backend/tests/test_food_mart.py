"""Integration against a fresh, isolated MySQL database upgraded to 0019."""
import asyncio
import base64
import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.db import Session, T, change, now, reflect, uid
from app.main import app
from app.menus import bounds, today
from app.shipping import prepare, record_quote

pytestmark = pytest.mark.asyncio


async def test_shared_stock_supplier_debt_prices_pickup_and_vat(monkeypatch):
    fixture = os.getenv('FOOD_MART_FIXTURE')
    if not fixture:
        pytest.skip('Requires an isolated Food Mart test database and account fixture')
    from app.config import settings
    from sqlalchemy.engine import make_url
    assert make_url(settings.database_url).database.startswith('ro_fm_fresh_')
    accounts = json.loads(Path(fixture).read_text(encoding='utf-8'))
    await reflect()
    transport = httpx.ASGITransport(app=app)
    sessions = []

    async def login(account):
        client = httpx.AsyncClient(transport=transport, base_url=settings.app_origin,
                                   headers={'Origin':settings.app_origin})
        sessions.append(client)
        response = await client.post('/api/v1/auth/login', json={'identifier':account['phone'],'password':account['password']})
        assert response.status_code == 200, response.text
        client.headers['X-CSRF-Token'] = response.json()['csrfToken']
        return client

    async def call(client, method, path, body=None, status=200, key=None):
        response = await client.request(method,'/api/v1'+path,json=body,
                                        headers={'Idempotency-Key':key or uid()})
        assert response.status_code == status, response.text
        return response.json()

    try:
        admin, student, worker = [await login(account) for account in accounts['accounts'][:3]]
        seller = await login(accounts['staffAccounts'][0])
        await call(seller,'GET','/shop/reports/overview',status=404)
        await call(admin,'GET','/admin/withdrawals',status=404)
        catalog = await call(admin,'GET','/admin/products')
        template = catalog[0]
        quick_name = 'Tạo nhanh '+uid()[:8]
        quick = {'name':quick_name,'categoryId':template['category_id'],'unitId':template['unit_id'],'quantityStep':'1'}
        await call(seller,'POST','/shop/products/bulk',{'items':[quick,{**quick,'name':''}]},status=400)
        assert not any(p['name']==quick_name for p in await call(seller,'GET','/shop/products'))
        bulk_key = uid()
        batch = await call(seller,'POST','/shop/products/bulk',{'items':[quick,{**quick,'name':quick_name+' B'}]},key=bulk_key)
        assert len(batch)==2 and batch[0]['sku'] != batch[1]['sku']
        replay = await call(seller,'POST','/shop/products/bulk',{'items':[quick,{**quick,'name':quick_name+' B'}]},key=bulk_key)
        assert [p['id'] for p in replay] == [p['id'] for p in batch]
        group_prices = [{'groupId':id,'unitPrice':'400'} for id in accounts['groups'].values()]
        products = [await call(seller,'POST','/shop/products',{'name':'Kho thử '+uid()[:8],
            'unitId':template['unit_id'],'categoryId':template['category_id'],'quantityStep':'1',
            'listPrice':'500'}) for _ in range(2)]
        other_category = next(row for row in await call(admin,'GET','/admin/config/categories')
                              if row['id'] != template['category_id'] and row['vat_rate'] is None)
        third = await call(seller,'POST','/shop/products',{'name':'Kho thử '+uid()[:8],
            'unitId':template['unit_id'],'categoryId':other_category['id'],'quantityStep':'1','listPrice':'500'})
        first, second = products
        products.append(third)
        supplier = await call(seller,'POST','/shop/stock/suppliers',{'name':'NCC thử '+uid()[:8],'contact':''})
        opening = {'kind':'OPENING','items':[{'productId':product['id'],'quantity':'1','unitCost':'100'} for product in products]}
        await call(seller,'POST','/shop/stock/receipts',{**opening,'paidAmount':'1'},status=400)
        await call(seller,'POST','/shop/stock/receipts',opening)
        await call(seller,'POST','/shop/stock/receipts',opening,status=409)
        purchase = {'supplierId':supplier['id'],'invoiceNumber':uid()[:8],'paidAmount':'200',
                    'items':[{'productId':first['id'],'quantity':'2','unitCost':'400'}]}
        bad_payment = await call(seller,'POST','/shop/stock/receipts',{**purchase,'paidAmount':'801'},status=400)
        assert bad_payment['error']['code'] == 'PAYMENT_EXCEEDS_RECEIPT'
        levels = {row['id']:row for row in await call(seller,'GET','/shop/stock')}
        assert Decimal(levels[first['id']]['quantity']) == 1
        key = uid()
        receipt = await call(seller,'POST','/shop/stock/receipts',purchase,key=key)
        assert Decimal(receipt['paid']) == 200 and Decimal(receipt['outstanding']) == 600
        assert (await call(seller,'POST','/shop/stock/receipts',purchase,key=key))['id'] == receipt['id']
        detail = await call(seller,'GET','/shop/stock/receipts/'+receipt['id'])
        assert len(detail['payments']) == 1 and Decimal(detail['payments'][0]['amount']) == 200
        levels = {row['id']:row for row in await call(seller,'GET','/shop/stock')}
        assert Decimal(levels[first['id']]['average_cost']) == 300
        assert Decimal(levels[first['id']]['quantity']) == 3
        pay_path = '/admin/supplier-payments/'+receipt['id']
        await call(seller,'POST',pay_path,{'amount':'250','reference':'first'},status=403)
        payment_key = uid()
        partial = await call(admin,'POST',pay_path,{'amount':'250','reference':'first'},key=payment_key)
        assert Decimal(partial['paid']) == 450 and Decimal(partial['outstanding']) == 350
        retry = await call(admin,'POST',pay_path,{'amount':'250','reference':'first'},key=payment_key)
        assert retry['id'] == partial['id']
        duplicate = await call(admin,'POST',pay_path,{'amount':'250','reference':'first'},status=409)
        assert duplicate['error']['code'] == 'DUPLICATE_PAYMENT'
        rejected = await call(admin,'POST',pay_path,{'amount':'351','reference':'over'},status=409)
        assert rejected['error']['code'] == 'PAYMENT_EXCEEDS_DEBT'
        debt = await call(seller,'GET','/shop/stock/receipts/'+receipt['id'])
        assert Decimal(debt['outstanding']) == 350
        settled = await call(admin,'POST',pay_path,{'amount':'350','reference':'second'})
        assert Decimal(settled['paid']) == 800 and Decimal(settled['outstanding']) == 0
        await call(admin,'POST',pay_path,{'amount':'1','reference':'after-settlement'},status=409)
        debt = await call(seller,'GET','/shop/stock/receipts/'+receipt['id'])
        assert Decimal(debt['outstanding']) == 0
        assert len(debt['payments']) == 3
        full = await call(seller,'POST','/shop/stock/receipts',{
            'supplierId':supplier['id'],'paidAmount':'101',
            'items':[{'productId':second['id'],'quantity':'1','unitCost':'101'}]})
        assert Decimal(full['outstanding']) == 0 and Decimal(full['paid']) == 101
        purchase_history = await call(seller,'GET','/shop/stock/receipts?kind=PURCHASE')
        assert {receipt['id'],full['id']} <= {r['id'] for r in purchase_history}
        assert all(r['kind']=='PURCHASE' for r in purchase_history)
        assert Decimal((await call(admin,'GET','/admin/supplier-summary'))['paid']) >= 800

        vat = await call(admin,'GET','/admin/vat')
        await call(admin,'PATCH','/admin/vat',{'rate':'10','expectedVersion':vat['version']})
        categories = await call(admin,'GET','/admin/config/categories')
        category = next(row for row in categories if row['id']==template['category_id'])
        await call(admin,'PATCH','/admin/vat/categories/'+category['id'],{'rate':'8','expectedVersion':category['version']})
        await call(admin,'PATCH','/admin/vat/products/'+first['id'],{'rate':'0','expectedVersion':first['version']})
        common = dict(name='Nhận hàng thử',addressLine='Điểm thử nghiệm')
        shared_slot = await call(admin,'POST','/admin/config/pickup-slots',common)
        student_slot = await call(admin,'POST','/admin/config/pickup-slots',
                                  {**common,'allowedGroupIds':[accounts['groups']['STUDENT']]})
        from app import commerce, menus
        day_start = bounds(today())[0]
        cutoff = day_start+timedelta(hours=17)
        before_cutoff = cutoff-timedelta(minutes=1)
        clock = [before_cutoff]
        real_time = now()
        starts = max(day_start,min(real_time,before_cutoff)-timedelta(minutes=1))
        menu_body = dict(saleDate=str(today()),status='OPEN',opensAt=starts.isoformat()+'Z',
                         closesAt=(max(real_time,cutoff)+timedelta(hours=2)).isoformat()+'Z',
                         pickupSlotIds=[shared_slot['id'],student_slot['id']],
                         items=[{'productId':p['id'],'availableQty':str(quantity),'listPrice':'500','prices':group_prices}
                                for p, quantity in zip(products, (3, 2, 1))])
        await call(seller,'POST','/shop/menus',{**menu_body,'items':[{**menu_body['items'][0],'listPrice':'399'}]},status=400)
        excessive = {**menu_body,'items':[{**menu_body['items'][0],'availableQty':'4'}]}
        rejected = await call(seller,'POST','/shop/menus',excessive,status=409)
        assert rejected['error']['code'] == 'MENU_STOCK_EXCEEDED'
        assert 'tồn kho chỉ còn 3 ' in rejected['error']['message']
        draft = await call(seller,'POST','/shop/menus',{**excessive,'status':'DRAFT'})
        draft_path = '/shop/menus/'+draft['id']
        rejected = await call(seller,'PATCH',draft_path,{'expectedVersion':draft['version'],'status':'OPEN'},status=409)
        assert rejected['error']['code'] == 'MENU_STOCK_EXCEEDED'
        assert (await call(seller,'GET',draft_path))['status'] == 'DRAFT'
        menu = await call(seller,'POST','/shop/menus',menu_body)
        first_item = menu_body['items'][0]
        menu_path = '/shop/menus/'+menu['id']
        line_version = next(item['version'] for item in menu['items'] if item['product_id']==first['id'])
        rejected = await call(seller,'PATCH',menu_path,{'expectedVersion':menu['version'],'items':[
            {**first_item,'availableQty':'4','expectedVersion':line_version}
        ]},status=409)
        assert rejected['error']['code'] == 'MENU_STOCK_EXCEEDED'
        unchanged = await call(seller,'GET',menu_path)
        assert unchanged['version'] == menu['version']
        assert {item['product_id']:Decimal(item['available_qty']) for item in unchanged['items']} == {
            product['id']:quantity for product, quantity in zip(products, (3, 2, 1))
        }
        duplicate = await call(seller,'POST','/shop/menus',{**menu_body,'items':[first_item,first_item]},status=400)
        assert duplicate['error']['code'] == 'DUPLICATE_ITEM'
        round_two = await call(seller,'POST','/shop/menus',{**menu_body,'items':[{
            **first_item,'prices':[{**price,'unitPrice':'450'} for price in group_prices]
        }]})
        monkeypatch.setattr(menus,'now',lambda:clock[0])
        monkeypatch.setattr(commerce,'now',lambda:clock[0])
        slots_path = '/delivery/options?menuId='+menu['id']
        worker_slots = (await call(worker,'GET',slots_path))['pickupSlots']
        assert {slot['id'] for slot in worker_slots} == {shared_slot['id']}
        assert worker_slots[0]['starts_at'] == cutoff.isoformat()+'Z'
        assert worker_slots[0]['ends_at'] == (cutoff+timedelta(hours=1)).isoformat()+'Z'
        assert {slot['id'] for slot in (await call(student,'GET',slots_path))['pickupSlots']} == {shared_slot['id'],student_slot['id']}
        student_post = next(post for post in (await call(student,'GET','/feed'))['posts'] if post['id']==menu['id'])
        worker_post = next(post for post in (await call(worker,'GET','/feed'))['posts'] if post['id']==menu['id'])
        assert {point['id'] for point in student_post['pickup_points']} == {shared_slot['id'],student_slot['id']}
        assert {point['id'] for point in worker_post['pickup_points']} == {shared_slot['id']}
        active_offers = await call(student,'GET','/catalog/offers')
        offers = {o['product_id']:o for o in active_offers if o['menu_id']==menu['id']}
        second_offer = next(o for o in active_offers if o['menu_id']==round_two['id'])
        assert second_offer['product_id'] == first['id'] and Decimal(second_offer['unit_price']) == 450
        assert offers[first['id']]['discount_percent'] == 20
        assert Decimal(offers[first['id']]['vat_rate']) == 0
        assert Decimal(offers[second['id']]['vat_rate']) == 8
        assert Decimal(offers[third['id']]['vat_rate']) == 10
        config = await call(student,'GET','/checkout/config')

        def line(product, quantity, offer=None):
            offer = offer or offers[product['id']]
            return dict(offerId=offer['id'],quantity=quantity,expectedPriceVersion=offer['price_version'],
                        expectedVatRate=offer['vat_rate'])

        def body(slot, items):
            return dict(clientOrderId=uid(),deliveryMethod='COLLECTIVE',pickupSlotId=slot['id'],
                        pickupSlotVersion=slot['version'],pickupStartsAt=cutoff.isoformat()+'Z',
                        items=items,vatVersion=config['vatVersion'])

        rejected = await call(worker,'POST','/orders',{**body(shared_slot,[line(first,'1')]),
                              'pickupStartsAt':(cutoff-timedelta(days=1)).isoformat()+'Z'},status=409)
        assert rejected['error']['code'] == 'REQUOTE_REQUIRED'
        clock[0] = cutoff
        assert not next(post for post in (await call(student,'GET','/feed'))['posts'] if post['id']==menu['id'])['pickup_points']
        assert not (await call(worker,'GET',slots_path))['pickupSlots']
        rejected = await call(worker,'POST','/orders',body(shared_slot,[line(first,'1')]),status=409)
        assert rejected['error']['code'] == 'PICKUP_CLOSED'
        clock[0] = before_cutoff
        mixed = await call(student,'POST','/orders',body(student_slot,[line(first,'1'),line(second,'1')]))
        assert Decimal(mixed['shipping_fee']) == 0 and Decimal(mixed['vat_amount']) == 32 and mixed['vat_rate'] is None
        assert mixed['delivery_snapshot']['pickupSlot']['starts_at'] == cutoff.isoformat()+'Z'
        await call(worker,'POST','/orders',body(student_slot,[line(first,'1')]),status=409)
        too_many = await call(worker,'POST','/orders',
                              body(shared_slot,[line(first,'3'),line(first,'1',second_offer)]),status=409)
        assert too_many['error']['code'] == 'INSUFFICIENT_STOCK'
        left = await call(student,'POST','/orders',body(shared_slot,[line(first,'3')]))
        right = await call(worker,'POST','/orders',body(shared_slot,[line(first,'3',second_offer)]))
        responses = await asyncio.gather(*[
            client.post('/api/v1/shop/orders/'+order['id']+'/approve',
                        json={'expectedVersion':order['version']},headers={'Idempotency-Key':uid()})
            for client,order in ((seller,left),(admin,right))
        ])
        assert sorted(r.status_code for r in responses) == [200,409], [r.text for r in responses]
        winner = next(r.json() for r in responses if r.status_code==200)
        assert Decimal(winner['items'][0]['cost_price_snapshot']) == 300
        shared_offer_ids = {offers[first['id']]['id'],second_offer['id']}
        current = await call(student,'GET','/catalog/offers')
        assert {o['id']:Decimal(o['available_qty']) for o in current if o['id'] in shared_offer_ids} == dict.fromkeys(shared_offer_ids,0)
        events = T['stream_events']
        async with Session() as s:
            update = await s.scalar(select(events.c.payload).where(
                events.c.topic=='catalog:'+accounts['groups']['STUDENT'],
                events.c.event_type=='CATALOG_CHANGED').order_by(events.c.seq.desc()).limit(1))
        assert {o['id'] for o in update['offers']} == shared_offer_ids
        buyer = student if winner['id']==left['id'] else worker
        cancel = await call(buyer,'POST','/orders/'+winner['id']+'/cancellation-requests',
                            {'expectedVersion':winner['version'],'reason':'Thử hoàn kho'})
        await call(seller,'POST','/shop/orders/'+winner['id']+'/decide-cancel',
                   {'expectedVersion':cancel['version'],'accept':True,'reason':'Đồng ý'})
        assert Decimal(next(row for row in await call(seller,'GET','/shop/stock') if row['id']==first['id'])['quantity']) == 3
        current = await call(student,'GET','/catalog/offers')
        assert {o['id']:Decimal(o['available_qty']) for o in current if o['id'] in shared_offer_ids} == dict.fromkeys(shared_offer_ids,3)
        history = await call(seller,'GET','/shop/stock/ledger?productId='+first['id'])
        assert {row['kind'] for row in history} >= {'OPENING','PURCHASE','APPROVE','CANCEL_RESTORE'}
        deleted_point = await call(admin,'DELETE','/admin/config/pickup-slots/'+student_slot['id'],
                                   {'expectedVersion':student_slot['version']})
        assert not deleted_point['active']
        remaining = (await call(student,'GET',slots_path))['pickupSlots']
        assert {slot['id'] for slot in remaining} == {shared_slot['id']}
        assert (await call(student,'GET','/orders/'+mixed['id']))['delivery_snapshot']['pickupSlot']['id'] == student_slot['id']
        monkeypatch.setattr(menus,'now',now)
        monkeypatch.setattr(commerce,'now',now)

        options = await call(student,'GET','/delivery/options')
        assert 'zones' not in options and len(options['policies']) == 1
        assert options['policies'][0]['group_id'] == accounts['groups']['STUDENT']
        duplicate_policy = await call(admin,'POST','/admin/config/policies',
                                      {'groupId':accounts['groups']['STUDENT']},status=409)
        assert duplicate_policy['error']['code'] == 'DELIVERY_POLICY_EXISTS'
        address = await call(student,'POST','/me/addresses',
                             {'recipientName':'Khách nhận mẫu','phone':accounts['accounts'][1]['phone'],
                              'addressLine':'Địa chỉ thử tính phí giao'})
        assert address['zone_id'] is None
        individual = dict(clientOrderId=uid(),addressId=address['id'],deliveryMethod='INDIVIDUAL',
                          vatVersion=config['vatVersion'],items=[line(first,'1')])
        async with Session.begin() as s:
            await change(s,'addresses',address['id'],latitude='20.99',longitude='105.80')
            prepared = await prepare(s, {'id':mixed['customer_id'],'group_id':accounts['groups']['STUDENT']}, individual)
            quote = await record_quote(s, {'id':mixed['customer_id'],'group_id':accounts['groups']['STUDENT']},
                                       prepared,(3000,600,{'provider':'FIXTURE','profile':'driving'}))
            individual.update(deliveryQuoteId=quote['id'],policyVersion=str(prepared[1]['version']))
        delivered = await call(student,'POST','/orders',individual)
        assert Decimal(delivered['shipping_fee']) == 9000
        assert 'zoneId' not in delivered['delivery_snapshot']
        approved = await call(seller,'POST','/shop/orders/'+delivered['id']+'/approve',{'expectedVersion':delivered['version']})
        prepared = await call(seller,'POST','/shop/orders/'+delivered['id']+'/transition',
                              {'expectedVersion':approved['version'],'status':'PREPARING'})
        assigned = await call(seller,'POST','/shop/orders/'+delivered['id']+'/assign',
                              {'expectedVersion':prepared['version'],'courierId':accounts['staffAccounts'][1]['id']})
        shipped = await call(seller,'POST','/shop/orders/'+delivered['id']+'/transition',
                             {'expectedVersion':assigned['version'],'status':'SHIPPING'})
        complete = await call(seller,'POST','/shop/orders/'+delivered['id']+'/transition',
                              {'expectedVersion':shipped['version'],'status':'DELIVERED','codAmount':shipped['total']})
        assert complete['payment_status']=='PAID'
        await call(student,'DELETE','/me/addresses/'+address['id'],{'expectedVersion':address['version']})
        report = await call(admin,'GET','/admin/reports/overview')
        assert Decimal(report['totals']['merchandise']) >= 400
        assert Decimal(report['totals']['grossProfit']) >= 100
        assert 'shops' not in report and 'platformFees' not in report['totals']

        from app import payments
        monkeypatch.setattr(payments,'configured',lambda: True)
        monkeypatch.setattr(payments.settings,'payos_checksum_key','fixture-checksum-not-a-live-key')
        link_id = uid().replace('-', '')
        async def fake_provider(method,path,payload=None,missing=False):
            if method=='GET':
                return None
            return {'orderCode':payload['orderCode'],'amount':payload['amount'],'paymentLinkId':link_id,
                    'checkoutUrl':'https://pay.payos.vn/web/'+link_id,'qrCode':'FIXTURE_ONLY'}
        monkeypatch.setattr(payments,'provider',fake_provider)
        monkeypatch.setattr(menus,'now',lambda:before_cutoff)
        monkeypatch.setattr(commerce,'now',lambda:before_cutoff)
        online = await call(student,'POST','/orders',{**body(shared_slot,[line(first,'1')]),'paymentMethod':'PAYOS'})
        await call(seller,'POST','/shop/orders/'+online['id']+'/approve',{'expectedVersion':online['version']})
        link = await call(student,'POST','/orders/'+online['id']+'/payment-link',{})
        assert link['receiver']=='STORE' and link['qr_image'].startswith('data:image/png;base64,')
        event = {'orderCode':link['order_code'],'paymentLinkId':link_id,'reference':uid(),
                 'amount':int(Decimal(link['amount'])),'currency':'VND','code':'00'}
        webhook = {'code':'00','success':True,'data':event,'signature':payments.signature(event)}
        await call(student,'POST','/payments/payos/webhook',webhook)
        await call(student,'POST','/payments/payos/webhook',webhook)
        assert (await call(student,'GET','/orders/'+online['id']))['payment_status']=='PAID'
        assert Decimal((await call(student,'GET','/orders/'+mixed['id']))['vat_amount'])==32

        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aHc8AAAAASUVORK5CYII=')
        files = {'file':('post.png',png,'image/png')}
        assert (await student.post('/api/v1/media',data={'purpose':'MENU_POST'},files=files)).status_code == 403
        upload = await seller.post('/api/v1/media',data={'purpose':'MENU_POST'},files=files)
        assert upload.status_code == 200, upload.text
        image = upload.json()
        asset_id = image['id']
        upload2 = await seller.post('/api/v1/media',data={'purpose':'MENU_POST'},files=files)
        assert upload2.status_code == 200, upload2.text
        image2 = upload2.json()
        post = await call(seller,'POST','/shop/menus',{**menu_body,'status':'DRAFT',
                          'allowedGroupIds':[accounts['groups']['STUDENT']],
                          'pickupSlotIds':[shared_slot['id']],
                          'items':[{**first_item,'availableQty':'1'}],
                          'postTitle':'Bài đăng có ảnh','postBody':'Thực phẩm hôm nay',
                          'postImages':[{'assetId':asset_id},{'assetId':image2['id']}]})
        assert post['post_image_asset_id'] == asset_id and post['post_image_url'] is None
        assert len(post['post_images']) == 2
        assert (await seller.get(image['url'])).status_code == 200
        assert (await student.get(image['url'])).status_code == 403
        post = await call(seller,'PATCH','/shop/menus/'+post['id'],
                          {'expectedVersion':post['version'],'status':'OPEN'})
        visible_post = next(p for p in (await call(student,'GET','/feed'))['posts'] if p['id']==post['id'])
        assert visible_post['post_title'] == 'Bài đăng có ảnh'
        assert visible_post['post_body'] == 'Thực phẩm hôm nay'
        assert visible_post['post_image_url'] == image['url']
        assert visible_post['post_images'] == [image['url'], image2['url']]
        assert (await student.get(image2['url'])).status_code == 200
        assert (await worker.get(image2['url'])).status_code == 403
        result = await student.get(image['url'])
        assert result.status_code == 200 and result.headers['content-type'] == 'image/jpeg'
        assert post['id'] not in {p['id'] for p in (await call(worker,'GET','/feed'))['posts']}
        assert (await worker.get(image['url'])).status_code == 403
        reactions_path='/feed/'+post['id']+'/reactions'
        await call(worker,'GET',reactions_path,status=403)
        await call(worker,'POST',reactions_path,{'reaction':'LIKE'},status=403)
        await call(student,'POST',reactions_path,{'reaction':'INVALID'},status=400)
        assert (await call(student,'GET',reactions_path)) == {'counts':{'LIKE':0,'LOVE':0,'WOW':0},'mine':None}
        reaction_key=uid()
        reacted=await call(student,'POST',reactions_path,{'reaction':'LIKE'},key=reaction_key)
        assert reacted['counts']['LIKE']==1 and reacted['mine']=='LIKE'
        assert (await call(student,'POST',reactions_path,{'reaction':'LIKE'},key=reaction_key))==reacted
        changed=await call(student,'POST',reactions_path,{'reaction':'LOVE'})
        assert changed['counts']=={'LIKE':0,'LOVE':1,'WOW':0} and changed['mine']=='LOVE'
        removed=await call(student,'POST',reactions_path,{'reaction':None})
        assert removed['counts']=={'LIKE':0,'LOVE':0,'WOW':0} and removed['mine'] is None
        comments_path='/feed/'+post['id']+'/comments'
        await call(worker,'GET',comments_path,status=403)
        await call(worker,'POST',comments_path,{'body':'Không có quyền'},status=403)
        comment_key=uid()
        comments=await call(student,'POST',comments_path,{'body':'Sản phẩm còn hàng không?'},key=comment_key)
        replay=await call(student,'POST',comments_path,{'body':'Sản phẩm còn hàng không?'},key=comment_key)
        assert len(comments)==len(replay)==1 and comments[0]['body']=='Sản phẩm còn hàng không?'
        assert (await call(student,'GET',comments_path))[0]['id']==comments[0]['id']
        await call(student,'POST',reactions_path,{'reaction':'WOW'})
        for operator,prefix in ((admin,'/admin'),(seller,'/shop')):
            listed=await call(operator,'GET',prefix+'/menus')
            entry=next(item for item in listed if item['id']==post['id'])
            assert entry['social']['commentCount']==1 and entry['social']['reactions']['WOW']==1
            social=await call(operator,'GET',prefix+'/menus/'+post['id']+'/social')
            assert social['comments'][0]['body']=='Sản phẩm còn hàng không?'
        await call(student,'GET','/admin/menus/'+post['id']+'/social',status=403)
        for operator in (admin,seller):
            assert any(n['kind']=='POST_INTERACTION' and n['payload']['menuId']==post['id'] for n in await call(operator,'GET','/notifications'))
        admin_comments='/admin/menus/'+post['id']+'/comments'
        root_id=comments[0]['id']
        reply=await call(admin,'POST',admin_comments,{'body':'Cửa hàng sẽ kiểm tra.','parentId':root_id})
        reply_row=next(row for row in reply if row['body']=='Cửa hàng sẽ kiểm tra.')
        assert reply_row['parent_id']==root_id and reply_row['role']=='ADMIN'
        customer_comments=await call(student,'GET',comments_path)
        assert any(row['id']==reply_row['id'] for row in customer_comments)
        await call(student,'POST',comments_path,{'body':'Không lồng sâu','parentId':reply_row['id']},status=400)
        assert any(n['kind']=='POST_INTERACTION' and n['payload']['menuId']==post['id'] for n in await call(student,'GET','/notifications'))
        assert not any(n['kind']=='POST_INTERACTION' and n['payload']['menuId']==post['id'] for n in await call(worker,'GET','/notifications'))
        admin_reactions='/admin/menus/'+post['id']+'/reactions'
        staff_reaction=await call(seller,'POST','/shop/menus/'+post['id']+'/reactions',{'reaction':'LOVE'})
        assert staff_reaction['mine']=='LOVE'
        assert (await call(admin,'GET',admin_reactions))['counts']['LOVE']==1
        await call(student,'GET',admin_comments,status=403)
        async with Session() as events:
            stream=T['stream_events']
            sent=(await events.execute(select(stream.c.topic,stream.c.event_type).where(
                stream.c.event_type.in_(['POST_COMMENTS_CHANGED','POST_REACTIONS_CHANGED'])))).all()
            assert ('admin:ops','POST_COMMENTS_CHANGED') in sent
            assert any(topic.startswith('shop:') and kind=='POST_REACTIONS_CHANGED' for topic,kind in sent)
        replaced = await call(seller,'PATCH','/shop/menus/'+post['id'],
                              {'expectedVersion':post['version'],'postImageUrl':'https://example.com/post.jpg'})
        assert replaced['post_image_asset_id'] is None and replaced['post_image_url']=='https://example.com/post.jpg'
        assert (await student.get(image['url'])).status_code == 403
        before={row['id']:Decimal(row['quantity']) for row in await call(seller,'GET','/shop/stock')}
        invalid={'supplierId':supplier['id'],'items':[{'productId':first['id'],'quantity':'0','unitCost':'200'},
                  {'productId':second['id'],'quantity':'1','unitCost':'-1'}]}
        error=await call(seller,'POST','/shop/stock/receipts',invalid,status=400)
        assert error['error']['code']=='INVALID_RECEIPT_LINES' and len(error['error']['details']['lines'])==2
        after={row['id']:Decimal(row['quantity']) for row in await call(seller,'GET','/shop/stock')}
        assert after[first['id']]==before[first['id']] and after[second['id']]==before[second['id']]
        multi={'supplierId':supplier['id'],'paidAmount':'250','items':[{'productId':first['id'],'quantity':'2','unitCost':'100'},
               {'productId':second['id'],'quantity':'3','unitCost':'200'}]}
        key=uid(); receipt=await call(seller,'POST','/shop/stock/receipts',multi,key=key)
        assert Decimal(receipt['total'])==800 and Decimal(receipt['outstanding'])==550
        assert (await call(seller,'POST','/shop/stock/receipts',multi,key=key))['id']==receipt['id']
        after={row['id']:Decimal(row['quantity']) for row in await call(seller,'GET','/shop/stock')}
        assert after[first['id']]==before[first['id']]+2 and after[second['id']]==before[second['id']]+3
    finally:
        for client in sessions:
            await client.aclose()
