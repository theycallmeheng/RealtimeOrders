"""Revenue isolation using SQL queries against a disposable in-memory database."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Column, Date, DateTime, MetaData, Numeric, String, Table, create_engine
from app import analytics, marketplace


@pytest.fixture
def sales(monkeypatch):
    metadata = MetaData()
    money = lambda name: Column(name, Numeric(18, 3))
    shops = Table('shops', metadata, Column('id', String, primary_key=True), Column('name', String))
    orders = Table('orders', metadata, Column('id', String, primary_key=True), Column('shop_id', String),
                   Column('status', String), Column('created_at', DateTime), Column('delivered_at', DateTime),
                   money('merchandise_total'), money('shipping_fee'), money('vat_amount'),
                   Column('payment_method', String), money('platform_fee'), money('platform_fee_rate'), Column('payment_status', String), money('total'))
    products = Table('products', metadata, Column('id', String, primary_key=True), Column('name', String))
    offers = Table('offers', metadata, Column('id', String, primary_key=True), Column('product_id', String))
    items = Table('order_items', metadata, Column('order_id', String), Column('offer_id', String),
                  money('quantity'), money('cost_price_snapshot'), money('line_total'), Column('unit_snapshot', String))
    entries = Table('money_entries', metadata, Column('order_id', String), Column('kind', String),
                    Column('method', String), money('amount'), Column('remitted_at', DateTime))
    Table('refund_requests', metadata, Column('id', String), Column('order_id', String), Column('state', String))
    withdrawals = Table('shop_withdrawals', metadata, Column('shop_id', String), Column('status', String),
                        money('amount'), Column('period_month', Date))
    engine = create_engine('sqlite://')
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(shops.insert(), [{'id':'a','name':'Food mart'}, {'id':'b','name':'Snack shop'}, {'id':'c','name':'No sales'}])
        for shop_id, revenue, cost, fee in [('a', 150000, 100000, 15000), ('b', 300000, None, 30000)]:
            connection.execute(orders.insert(), dict(id=shop_id, shop_id=shop_id, status='DELIVERED',
                created_at=datetime(2026,11,8,2), delivered_at=datetime(2026,11,8,3),
                merchandise_total=revenue, shipping_fee=10000, vat_amount=0, payment_method='COD', platform_fee=fee, platform_fee_rate=10, payment_status='PAID', total=revenue+10000))
            connection.execute(products.insert(), dict(id=shop_id, name='Product '+shop_id))
            connection.execute(offers.insert(), dict(id=shop_id, product_id=shop_id))
            connection.execute(items.insert(), dict(order_id=shop_id, offer_id=shop_id, quantity=1,
                cost_price_snapshot=cost, line_total=revenue, unit_snapshot='kg'))
        # An uncompleted order must affect created counts, but not revenue.
        connection.execute(orders.insert(), dict(id='pending', shop_id='b', status='PENDING',
            created_at=datetime(2026,11,8,4), merchandise_total=900000, shipping_fee=0, vat_amount=0, platform_fee=0))
        connection.execute(entries.insert(), [dict(order_id='a', kind='PAYMENT', method='COD', amount=160000, remitted_at=datetime(2026,11,8,4)),
            dict(order_id='b', kind='PAYMENT', method='COD', amount=310000, remitted_at=None)])
        connection.execute(withdrawals.insert(), [dict(shop_id='a', status='PENDING', amount=10000, period_month=analytics.today().replace(day=1)),
            dict(shop_id='a', status='PAID', amount=5000, period_month=analytics.today().replace(day=1))])
        monkeypatch.setattr(analytics, 'T', metadata.tables)
        monkeypatch.setattr(marketplace, 'T', metadata.tables)
        class Session:
            async def execute(self, query):
                return connection.execute(query)
        yield Session()
    engine.dispose()


@pytest.mark.asyncio
async def test_overview_isolates_shops_and_unknown_costs(sales):
    result = await analytics.overview(sales, '2026-11-08', '2026-11-08', 'a')
    assert result['shopId'] == 'a'
    assert result['totals']['createdOrders'] == 1
    assert result['totals']['orders'] == 1
    assert result['totals']['merchandise'] == Decimal(150000)
    assert result['totals']['grossProfit'] == Decimal(50000)
    assert result['totals']['platformFees'] == Decimal(15000)
    assert result['totals']['afterPlatformFees'] == Decimal(135000)
    assert result['totals']['profitAfterFees'] == Decimal(35000)
    assert [p['productId'] for p in result['topProducts']] == ['a']
    assert [shop['shopId'] for shop in result['shops']] == ['a']
    other = await analytics.overview(sales, '2026-11-08', '2026-11-08', 'b')
    assert other['totals']['createdOrders'] == 2
    assert other['totals']['grossProfit'] is None


@pytest.mark.asyncio
async def test_all_shop_breakdown_reconciles_and_includes_zero_sales(sales):
    result = await analytics.overview(sales, '2026-11-08', '2026-11-08')
    assert result['shopId'] is None
    assert sum(shop['merchandise'] for shop in result['shops']) == result['totals']['merchandise'] == Decimal(450000)
    assert sum(shop['platformFees'] for shop in result['shops']) == result['totals']['platformFees'] == Decimal(45000)
    assert result['totals']['grossProfit'] is None
    assert next(shop for shop in result['shops'] if shop['shopId']=='a')['grossProfit'] == Decimal(50000)
    assert next(shop for shop in result['shops'] if shop['shopId']=='c')['orders'] == 0


@pytest.mark.asyncio
async def test_day_and_month_keep_scope_in_comparisons_and_series(sales):
    daily = await analytics.report(sales, '2026-11-08', '2026-11-07', 'a')
    assert daily['shopId'] == 'a'
    assert daily['selected']['merchandise'] == '150000.000'
    assert daily['comparison']['orders'] == 0
    assert len(daily['daily']) == 7
    monthly = await analytics.monthly_report(sales, '2026-11', '2026-10', 'a')
    assert monthly['shopId'] == 'a'
    assert Decimal(monthly['selected']['merchandise']) == Decimal(150000)
    assert monthly['selected']['grossProfit'] is not None
    assert sum(row['orders'] for row in monthly['daily']) == 1


@pytest.mark.asyncio
async def test_balance_uses_after_fee_receipts_less_withdrawals(sales):
    result = await marketplace.balance(sales, 'a')
    assert result['available'] == Decimal(120000)  # 150000 - 15000 - 10000 - 5000
    assert result['fees'] == Decimal(15000)
    assert (await marketplace.balance(sales, 'b'))['available'] == 0  # COD not remitted


@pytest.mark.asyncio
async def test_new_order_fee_is_ten_percent_of_merchandise(monkeypatch):
    async def policy(session): return {'rate':'10','version':'1'}
    monkeypatch.setattr(marketplace, 'fee_policy', policy)
    rate, fee = await marketplace.order_fee(None, Decimal('150005'))
    assert rate == Decimal(10) and fee == Decimal(15001)
