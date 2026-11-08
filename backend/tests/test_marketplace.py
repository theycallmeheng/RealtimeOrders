"""Marketplace rules over TCP on the isolated MySQL copy."""
import asyncio
from decimal import Decimal
from uuid import uuid4

import httpx
from sqlalchemy import select

from app import menus
from app.db import Session, T, uid, now
from conftest import Client, ORIGIN
from test_shop_workflow import assign, roles


async def test_shop_ownership_and_monthly_withdrawals(clients, roles, sale):
    admin, buyer = clients[:2]
    legacy_seller, courier, _ = roles
    phone = '+849' + str(uuid4().int % 100000000).zfill(8)
    password = 'IsolatedOwner123!'
    async with httpx.AsyncClient(base_url=ORIGIN, verify=False, timeout=30, headers={'Origin': ORIGIN}) as http:
        challenge = (await http.post('/api/v1/auth/registration/otp', json={'phone': phone})).json()
        verification = (await http.post('/api/v1/auth/registration/verify', json={
            'challengeId': challenge['challengeId'], 'code': challenge['demoCode'],
        })).json()
        registered = await http.post('/api/v1/auth/register', json={
            'ticket': verification['ticket'], 'displayName': 'Audit shop owner', 'password': password,
        })
        assert registered.status_code == 200, registered.text
        login = await http.post('/api/v1/auth/login', json={'identifier': phone, 'password': password})
        assert login.status_code == 200, login.text
        applicant = Client(http, login.json())
        application = await applicant.post('/marketplace/application', {
            'name': 'Audit shop ' + uid()[:8], 'address': 'Hà Đông, Hà Nội',
        })
        decision = await admin.request('PATCH', '/admin/shop-applications/' + application['id'], {
            'approved': True, 'expectedVersion': application['version'],
        })
        assert decision.status_code == 200, decision.text
        shop_id = decision.json()['shop_id']
        assert (await applicant.request('GET', '/auth/session')).status_code == 401
        login = await http.post('/api/v1/auth/login', json={'identifier': phone, 'password': password})
        assert login.status_code == 200, login.text
        seller = Client(http, login.json())
        assert seller.user['role'] == 'SELLER' and seller.user['shop_id'] == shop_id
        assert await seller.get('/shop/products') == []
        overview = await seller.get('/shop/reports/overview')
        assert overview['shopId'] == shop_id and [row['shopId'] for row in overview['shops']] == [shop_id]
        assert (await seller.request('GET', '/shop/reports/overview?shopId=' + legacy_seller.user['shop_id'])).status_code == 403
        assert (await buyer.request('GET', '/shop/reports/overview')).status_code == 403
        assert (await seller.get('/shop/reports/daily'))['shopId'] == shop_id
        assert (await seller.get('/shop/reports/monthly'))['shopId'] == shop_id

        legacy = next(row for row in await admin.get('/admin/products') if row['id'] == sale['product_id'])
        product = await seller.post('/shop/products', {
            'name': 'Audit other shop product', 'categoryId': legacy['category_id'], 'unitId': legacy['unit_id'],
            'quantityStep': '1', 'defaultCostPrice': '1300000',
        })
        assert product['shop_id'] == shop_id
        assert (await legacy_seller.request('PATCH', '/shop/products/' + product['id'], {})).status_code == 403
        menu = await seller.post('/shop/menus', {
            'saleDate': str(menus.today()), 'status': 'OPEN',
            'items': [{'productId': product['id'], 'availableQty': '3', 'salePrice': '2000000'}],
        })
        assert (await legacy_seller.request('GET', '/shop/menus/' + menu['id'])).status_code == 403
        offers = await buyer.get('/catalog/offers?shopId=' + shop_id)
        assert len(offers) == 1 and Decimal(offers[0]['unit_price']) == Decimal('2000000')
        assert 'cost_price' not in offers[0]
        offer = offers[0]
        legacy_offer = next(item for item in await buyer.get('/catalog/offers') if item['id'] == sale['id'])
        mixed = await buyer.request('POST', '/orders', {'clientOrderId': uid(), 'items': [
            {'offerId': item['id'], 'quantity': '1', 'expectedPriceVersion': item['price_version']}
            for item in (offer, legacy_offer)
        ]})
        assert mixed.status_code == 409 and mixed.json()['error']['code'] == 'MIXED_SHOPS', mixed.text
        other_chat = await buyer.get('/conversations/me?shopId=' + shop_id)
        legacy_chat = await buyer.get('/conversations/me')
        assert other_chat['id'] != legacy_chat['id']
        assert (await legacy_seller.request('GET', '/conversations/' + other_chat['id'] + '/messages')).status_code == 403

        bank = {'bankName': 'Ngân hàng kiểm thử', 'accountHolder': 'Audit', 'accountNumber': '00123456'}
        response = await seller.request('PATCH', '/shop/bank', bank)
        assert response.status_code == 200, response.text
        blocked = await seller.request('POST', '/shop/withdrawals', {'amount': '1'})
        assert blocked.status_code == 409 and blocked.json()['error']['code'] == 'BALANCE_MINIMUM'
        fee = await admin.get('/admin/platform-fee')
        try:
            response = await admin.request('PATCH', '/admin/platform-fee', {'rate': '5', 'expectedVersion': fee['version']})
            assert response.status_code == 200, response.text
            options = await buyer.get('/delivery/options?shopId=' + shop_id)
            slot = options['pickupSlots'][0]
            policy = next(row for row in options['policies'] if row['method'] == 'COLLECTIVE')
            addr = next(row for row in await buyer.get('/me/addresses') if row['zone_id'] == policy['zone_id'])
            order = await buyer.post('/orders', {
                'clientOrderId': uid(), 'addressId': addr['id'], 'deliveryMethod': 'COLLECTIVE',
                'pickupSlotId': slot['id'], 'pickupSlotVersion': slot['version'], 'policyVersion': policy['version'],
                'items': [{'offerId': offer['id'], 'quantity': '1', 'expectedPriceVersion': offer['price_version']}],
            })
        finally:
            current = await admin.get('/admin/platform-fee')
            await admin.request('PATCH', '/admin/platform-fee', {'rate': fee['rate'], 'expectedVersion': current['version']})
        assert order['shop_id'] == shop_id and 'platform_fee' not in order
        assert (await legacy_seller.request('GET', '/orders/' + order['id'])).status_code == 403
        assert (await legacy_seller.request('POST', '/shop/orders/' + order['id'] + '/approve', {
            'expectedVersion': order['version'],
        })).status_code == 403
        order = await seller.post('/shop/orders/' + order['id'] + '/approve', {'expectedVersion': order['version']})
        order = await assign(seller, order, courier)
        for status in ('PREPARING', 'READY_FOR_PICKUP'):
            order = await seller.post('/shop/orders/' + order['id'] + '/transition', {
                'expectedVersion': order['version'], 'status': status,
            })
        order = await courier.post('/courier/orders/' + order['id'] + '/transition', {
            'expectedVersion': order['version'], 'status': 'DELIVERED', 'codAmount': order['total'],
        })
        assert Decimal((await seller.get('/shop/balance'))['balance']['available']) == 0
        async with Session() as db:
            entry_id = (await db.execute(select(T['money_entries'].c.id).where(
                T['money_entries'].c.order_id == order['id'],
            ))).scalar_one()
        await admin.post('/shop/money/' + entry_id + '/remit', {'received': True})
        balance = (await seller.get('/shop/balance'))['balance']
        assert Decimal(balance['available']) == 1900000 and Decimal(balance['fees']) == 100000
        too_much = await seller.request('POST', '/shop/withdrawals', {'amount': '1900001'})
        assert too_much.status_code == 400
        key = uid()
        first, duplicate = await asyncio.gather(
            seller.post('/shop/withdrawals', {'amount': '200000'}, key),
            seller.post('/shop/withdrawals', {'amount': '200000'}, key),
        )
        assert first['id'] == duplicate['id']
        second = await seller.post('/shop/withdrawals', {'amount': '100000'})
        third = await seller.request('POST', '/shop/withdrawals', {'amount': '1000'})
        assert third.status_code == 409 and third.json()['error']['code'] == 'WITHDRAWAL_LIMIT'
        # A pending withdrawal cannot be paid if its backing funds disappear.
        async with Session.begin() as db:
            await db.execute(T['money_entries'].update().where(T['money_entries'].c.id == entry_id).values(remitted_at=None))
        unfunded = await admin.request('PATCH', '/admin/withdrawals/' + first['id'], {
            'expectedVersion': first['version'], 'status': 'PAID', 'reference': 'unfunded-' + uid(),
        })
        assert unfunded.status_code == 409 and unfunded.json()['error']['code'] == 'INSUFFICIENT_SETTLED_BALANCE'
        async with Session.begin() as db:
            await db.execute(T['money_entries'].update().where(T['money_entries'].c.id == entry_id).values(remitted_at=now()))
        paid = await admin.request('PATCH', '/admin/withdrawals/' + first['id'], {
            'expectedVersion': first['version'], 'status': 'PAID', 'reference': 'audit-' + uid(),
        })
        assert paid.status_code == 200, paid.text
        rejected = await admin.request('PATCH', '/admin/withdrawals/' + second['id'], {
            'expectedVersion': second['version'], 'status': 'REJECTED', 'note': 'Kiểm thử hoàn lượt',
        })
        assert rejected.status_code == 200, rejected.text
        assert (await seller.request('GET', '/admin/withdrawals')).status_code == 403
        assert not (await legacy_seller.get('/shop/balance'))['withdrawals']
        data = await seller.get('/shop/balance')
        assert Decimal(data['balance']['available']) == 1700000
        assert data['balance']['used'] == 1 and Decimal(data['balance']['paid']) == 200000
        await seller.post('/shop/withdrawals', {'amount': '300000'})
