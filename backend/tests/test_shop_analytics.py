"""Storewide revenue using SQL queries against a disposable in-memory database."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Column, Date, DateTime, MetaData, Numeric, String, Table, create_engine
from app import analytics


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
        class Session:
            async def execute(self, query):
                return connection.execute(query)
        yield Session()
    engine.dispose()


@pytest.mark.asyncio
async def test_overview_combines_historical_sales_and_keeps_unknown_costs(sales):
    result = await analytics.overview(sales, '2026-11-08', '2026-11-08')
    assert result['totals']['createdOrders'] == 3
    assert result['totals']['orders'] == 2
    assert result['totals']['merchandise'] == Decimal(450000)
    assert result['totals']['grossProfit'] is None
    assert [p['productId'] for p in result['topProducts']] == ['b','a']
    assert result['topProducts'][1]['grossProfit'] == Decimal(50000)
    assert 'shops' not in result and 'platformFees' not in result['totals']


@pytest.mark.asyncio
async def test_daily_and_monthly_reports_reconcile_across_legacy_shop_ids(sales):
    daily = await analytics.report(sales, '2026-11-08', '2026-11-07')
    assert Decimal(daily['selected']['merchandise']) == Decimal(450000)
    assert daily['comparison']['orders'] == 0
    assert len(daily['daily']) == 7
    monthly = await analytics.monthly_report(sales, '2026-11', '2026-10')
    assert Decimal(monthly['selected']['merchandise']) == Decimal(450000)
    assert monthly['selected']['grossProfit'] is None
    assert sum(row['orders'] for row in monthly['daily']) == 2
