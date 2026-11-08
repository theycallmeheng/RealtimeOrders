"""Exercise QR, signed receipts and shop balances without contacting a bank."""
import base64
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Text, create_engine
from app import db, marketplace, payments


@pytest.fixture
def platform(monkeypatch):
    metadata = MetaData()
    money = lambda name: Column(name, Numeric(18, 0))
    shops = Table('shops', metadata, Column('id', String, primary_key=True))
    orders = Table('orders', metadata, Column('id', String, primary_key=True), Column('shop_id', String),
        Column('customer_id', String), Column('courier_id', String), Column('status', String),
        Column('payment_method', String), Column('payment_status', String), Column('version', Integer),
        Column('updated_at', DateTime), Column('payment_deadline', DateTime), money('total'),
        money('merchandise_total'), money('platform_fee'), money('platform_fee_rate'))
    requests = Table('payment_requests', metadata, Column('id', String, primary_key=True),
        Column('order_id', String), Column('order_code', Integer), money('amount'), Column('state', String),
        Column('expires_at', DateTime), Column('updated_at', DateTime), Column('checkout_url', Text),
        Column('provider_link_id', String), Column('qr_code', Text), Column('account_name', String),
        Column('account_number', String), Column('bank_bin', String))
    entries = Table('money_entries', metadata, Column('id', String, primary_key=True), Column('order_id', String),
        Column('kind', String), Column('method', String), money('amount'), Column('provider_ref', String, unique=True),
        Column('created_at', DateTime), Column('remitted_at', DateTime))
    Table('refund_requests', metadata, Column('id', String), Column('order_id', String), Column('state', String),
        money('amount'), Column('created_at', DateTime), Column('completed_at', DateTime),
        Column('completed_by', String), Column('reference', String), Column('note', String))
    Table('shop_withdrawals', metadata, Column('shop_id', String), Column('status', String), money('amount'), Column('period_month', Date))
    engine = create_engine('sqlite://')
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(shops.insert(), dict(id='shop-a'))
        connection.execute(orders.insert(), dict(id='order-a', shop_id='shop-a', customer_id='buyer', status='APPROVED',
            payment_method='PAYOS', payment_status='UNPAID', version=1, total=110000, merchandise_total=100000,
            platform_fee=10000, platform_fee_rate=10, payment_deadline=db.now()+timedelta(minutes=15)))
        connection.execute(requests.insert(), dict(id='req-a', order_id='order-a', order_code=100001, amount=110000,
            state='CREATING', expires_at=db.now()+timedelta(minutes=15)))
        for module in (db, marketplace, payments): monkeypatch.setattr(module, 'T', metadata.tables)
        class Session:
            def __init__(self): self.info = {}
            async def execute(self, query): return connection.execute(query)
            @asynccontextmanager
            async def begin(self): yield self
        session = Session()
        monkeypatch.setattr(payments, 'Session', session)
        monkeypatch.setattr(payments, 'configured', lambda: True)
        monkeypatch.setattr(payments.settings, 'payos_checksum_key', 'test-only-checksum')
        async def notify(*args, **kwargs): pass
        monkeypatch.setattr(payments, 'notify', notify)
        yield session
    engine.dispose()


def signed(amount=110000, reference='test-transfer'):
    data = {'orderCode':100001, 'amount':amount, 'reference':reference, 'paymentLinkId':'a'*32, 'currency':'VND', 'code':'00'}
    return {'code':'00', 'success':True, 'data':data, 'signature':payments.signature(data)}


@pytest.mark.asyncio
async def test_qr_is_persisted_and_retry_does_not_create_another_link(platform, monkeypatch):
    calls = []
    async def provider(method, path, payload=None, **kwargs):
        calls.append(method)
        if method == 'GET': return None
        return {'orderCode':100001, 'amount':110000, 'paymentLinkId':'a'*32,
            'checkoutUrl':'https://pay.payos.vn/web/'+'a'*32, 'qrCode':'TEST-ONLY-NOT-A-BANK-QR',
            'accountName':'Platform test account', 'accountNumber':'TEST123', 'bin':'970000'}
    monkeypatch.setattr(payments, 'provider', provider)
    first = await payments.link({'id':'buyer','role':'CUSTOMER'}, 'order-a')
    second = await payments.link({'id':'buyer','role':'CUSTOMER'}, 'order-a')
    assert calls == ['GET','POST']
    assert first == second and first['receiver'] == 'PLATFORM'
    assert first['account_name'] == 'Platform test account'
    assert base64.b64decode(first['qr_image'].split(',')[1]).startswith(b'\x89PNG\r\n\x1a\n')
    assert 'qr_code' not in first and 'payos_checksum_key' not in first
    with pytest.raises(db.Fault): await payments.link({'id':'other','role':'CUSTOMER'}, 'order-a')


@pytest.mark.asyncio
async def test_signed_receipt_only_credits_shop_after_delivery_once(platform):
    body = signed()
    await payments.webhook(platform, body)
    await payments.webhook(platform, body)
    assert (await payments.summary(platform, await db.one(platform, 'orders', payments.T['orders'].c.id=='order-a')))['remaining'] == 0
    balance = await marketplace.balance(platform, 'shop-a')
    assert balance['available'] == 0 and balance['held'] == 90000
    await db.change(platform, 'orders', 'order-a', status='DELIVERED')
    balance = await marketplace.balance(platform, 'shop-a')
    assert balance['available'] == 90000 and balance['held'] == 0
    assert (await marketplace.balance(platform, 'shop-b'))['available'] == 0


@pytest.mark.asyncio
async def test_invalid_signature_partial_and_cancelled_payments_cannot_be_withdrawn(platform):
    with pytest.raises(db.Fault): await payments.webhook(platform, {**signed(), 'signature':'bad'})
    await payments.webhook(platform, signed(1000))
    assert (await db.one(platform, 'orders', payments.T['orders'].c.id=='order-a'))['payment_status'] == 'UNPAID'
    assert (await marketplace.balance(platform, 'shop-a'))['held'] == 0
    await db.change(platform, 'orders', 'order-a', status='CANCELLED')
    await payments.webhook(platform, signed(109000, 'late-transfer'))
    order = await db.one(platform, 'orders', payments.T['orders'].c.id=='order-a')
    assert order['payment_status'] == 'REFUND_PENDING'
    assert (await marketplace.balance(platform, 'shop-a'))['available'] == 0


def test_mismatched_provider_order_cannot_be_reconciled():
    with pytest.raises(db.Fault): payments.validate_remote({'order_code':100001,'amount':Decimal(110000)}, {'orderCode':2,'amount':110000})


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['101', '231'])
async def test_provider_missing_lookup_allows_first_link_creation(monkeypatch, code):
    import httpx
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, *args, **kwargs):
            return httpx.Response(200, json={'code':code,'desc':'Payment link does not exist'})
    monkeypatch.setattr(payments.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(payments, 'configured', lambda: True)
    assert await payments.provider('GET', '/100001', missing=True) is None
    # Other calls must still report the failure, not silently return success.
    with pytest.raises(db.Fault): await payments.provider('GET', '/100001')
    with pytest.raises(db.Fault): await payments.provider('POST', '', {}, missing=True)


@pytest.mark.asyncio
async def test_provider_auth_failure_does_not_allow_link_creation(monkeypatch):
    import httpx
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, *args, **kwargs):
            return httpx.Response(401, json={'code':'401','desc':'Unauthorized'})
    monkeypatch.setattr(payments.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(payments, 'configured', lambda: True)
    with pytest.raises(db.Fault): await payments.provider('GET', '/100001', missing=True)
