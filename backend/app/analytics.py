"""Vietnamese business-day revenue and gross profit; unknown costs stay unknown."""
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import select, or_, and_, func
from .db import T,check,public
from .menus import bounds,today,VN


async def report(s, day=None, compare=None, shop_id=None):
    try:
        day=date.fromisoformat(day) if day else today()
        compare=date.fromisoformat(compare) if compare else day-timedelta(days=1)
    except ValueError: check(False,'INVALID_DATE','Ngày báo cáo không hợp lệ')
    dates=sorted({compare,*(day-timedelta(days=n) for n in range(7))})
    daily=await daily_records(s,dates,shop_id)
    selected=daily[str(day)];reference=daily[str(compare)]
    changes=compare_records(selected,reference)
    return public({'shopId':shop_id,'timezone':'Asia/Ho_Chi_Minh','selected':selected,'comparison':reference,'changes':changes,
                   'daily':[daily[str(day-timedelta(days=n))] for n in reversed(range(7))]})


async def daily_records(s, dates, shop_id=None):
    daily, _, _ = await sales_records(s, dates, shop_id=shop_id)
    return daily


async def sales_records(s, dates, include_products=False, shop_id=None):
    dates=sorted(set(dates))
    product_sales = {}
    daily={str(d):{'day':str(d),'orders':0,'merchandise':Decimal(0),'shipping':Decimal(0),
                   'cost':Decimal(0),'grossProfit':Decimal(0),'missingCostLines':0,'vat':Decimal(0),'legacyPaymentOrders':0,'platformFees':Decimal(0)} for d in dates}
    shops = {}
    if include_products:
        query = select(T['shops'].c.id, T['shops'].c.name)
        if shop_id: query = query.where(T['shops'].c.id == shop_id)
        for shop in (await s.execute(query)).mappings():
            shops[shop['id']] = {**next(iter(daily.values())), 'shopId':shop['id'], 'name':shop['name']}
            shops[shop['id']].pop('day', None)
    o,i=T['orders'],T['order_items']
    # Query only requested contiguous windows, even for distant comparison dates.
    windows=[]
    for d in dates:
        if windows and d==windows[-1][1]+timedelta(days=1): windows[-1]=(windows[-1][0],d)
        else: windows.append((d,d))
    intervals=[and_(o.c.delivered_at>=bounds(a)[0],o.c.delivered_at<bounds(b)[1]) for a,b in windows]
    orders=(await s.execute(select(o.c.id,o.c.delivered_at,o.c.merchandise_total,o.c.shipping_fee,o.c.vat_amount,o.c.payment_method,o.c.shop_id,o.c.platform_fee)
        .where(o.c.status=='DELIVERED',or_(*intervals),*([o.c.shop_id==shop_id] if shop_id else [])))).mappings().all()
    by_id={row['id']:str((row['delivered_at']+VN).date()) for row in orders}
    for row in orders:
        record=daily.get(by_id[row['id']])
        if record is not None:
            for target in [record] + ([shops[row['shop_id']]] if row['shop_id'] in shops else []):
                target['orders']+=1;target['merchandise']+=row['merchandise_total'];target['shipping']+=row['shipping_fee']
                target['vat']+=row['vat_amount'];target['legacyPaymentOrders']+=int(row['payment_method']=='LEGACY')
                target['platformFees'] += row['platform_fee'] or Decimal(0)
    order_shops={row['id']:row['shop_id'] for row in orders}
    if by_id:
        items = select(i.c.order_id, i.c.quantity, i.c.cost_price_snapshot)
        if include_products:
            offer, product = T['offers'], T['products']
            items = items.add_columns(
                product.c.id.label('product_id'), product.c.name,
                i.c.unit_snapshot, i.c.line_total,
            ).join(offer, i.c.offer_id == offer.c.id).join(product, offer.c.product_id == product.c.id)
        for item in (await s.execute(items.where(i.c.order_id.in_(by_id)))).mappings():
            record = daily[by_id[item['order_id']]]
            cost = item['cost_price_snapshot']
            line_cost = None if cost is None else (item['quantity'] * cost).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            for target in [record] + ([shops[order_shops[item['order_id']]]] if order_shops[item['order_id']] in shops else []):
                if line_cost is None:
                    target['missingCostLines'] += 1
                else:
                    target['cost'] += line_cost
            if include_products:
                # Keep quantities from different historical units separate.
                key = (item['product_id'], item['unit_snapshot'])
                ranked = product_sales.setdefault(key, {
                    'productId': key[0], 'unit': key[1], 'name': item['name'],
                    'quantity': Decimal(0), 'merchandise': Decimal(0), 'grossProfit': Decimal(0),
                })
                ranked['quantity'] += item['quantity']
                ranked['merchandise'] += item['line_total']
                if line_cost is None:
                    ranked['grossProfit'] = None
                elif ranked['grossProfit'] is not None:
                    ranked['grossProfit'] += item['line_total'] - line_cost
    for record in [*daily.values(), *shops.values()]:
        if record['missingCostLines']:record['cost']=None;record['grossProfit']=None
        else: record['grossProfit']=record['merchandise']-record['cost']
        record['afterPlatformFees']=record['merchandise']-record['platformFees']
        record['profitAfterFees']=None if record['grossProfit'] is None else record['grossProfit']-record['platformFees']
    return daily, product_sales, list(shops.values())


def compare_records(selected,reference):
    changes={}
    for field in ('merchandise','grossProfit','orders'):
        a,b=selected[field],reference[field]
        changes[field]={'amount':None if a is None or b is None else a-b,
            'percent':None if a is None or b in (None,0) else ((Decimal(a)-Decimal(b))*100/abs(Decimal(b))).quantize(Decimal('.01'))}
    return changes


def month_days(value):
    import re,calendar
    check(isinstance(value,str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}',value) is not None,
          'INVALID_DATE','Tháng báo cáo phải có dạng YYYY-MM')
    year,month=map(int,value.split('-'))
    check(1<=year<=9998 and 1<=month<=12,'INVALID_DATE','Tháng báo cáo không hợp lệ')
    return [date(year,month,d) for d in range(1,calendar.monthrange(year,month)[1]+1)]


def sales_totals(records):
    result = {}
    for field in ('orders','merchandise','shipping','missingCostLines','vat','legacyPaymentOrders','platformFees'):
        result[field]=sum(r.get(field,0) for r in records)
    result['cost']=None if result['missingCostLines'] else sum(r['cost'] for r in records)
    result['grossProfit']=None if result['cost'] is None else result['merchandise']-result['cost']
    result['afterPlatformFees']=result['merchandise']-result['platformFees']
    result['profitAfterFees']=None if result['grossProfit'] is None else result['grossProfit']-result['platformFees']
    return result


def month_total(month, records):
    return {'month': month, **sales_totals(records)}


async def overview(s, start=None, end=None, shop_id=None):
    try:
        last_day = date.fromisoformat(end) if end is not None else today()
        first_day = date.fromisoformat(start) if start is not None else last_day - timedelta(days=6)
    except (ValueError, OverflowError):
        check(False, 'INVALID_DATE', 'Ngày thống kê không hợp lệ')
    check(date(1000, 1, 2) <= first_day <= last_day <= date(9999, 12, 30),
          'INVALID_DATE', 'Khoảng ngày thống kê không hợp lệ')
    days = (last_day - first_day).days + 1
    check(days <= 366, 'INVALID_DATE', 'Chọn khoảng tối đa 366 ngày')
    records, products, shops = await sales_records(
        s, [first_day + timedelta(days=n) for n in range(days)], include_products=True, shop_id=shop_id,
    )
    daily = list(records.values())
    totals = sales_totals(daily)
    orders = T['orders']
    created_by_status = (await s.execute(
        select(orders.c.status, func.count().label('count')).where(
            orders.c.created_at >= bounds(first_day)[0], orders.c.created_at < bounds(last_day)[1],
            *([orders.c.shop_id == shop_id] if shop_id else []),
        ).group_by(orders.c.status).order_by(func.count().desc(), orders.c.status)
    )).mappings().all()
    totals['createdOrders'] = sum(row['count'] for row in created_by_status)
    totals['averageOrderValue'] = (totals['merchandise'] / totals['orders']).quantize(
        Decimal(1), rounding=ROUND_HALF_UP,
    ) if totals['orders'] else None
    ranked = sorted(products.values(), key=lambda row: (-row['merchandise'], row['name'], row['productId'], row['unit']))
    return {
        'shopId':shop_id, 'shops':sorted(shops, key=lambda row: (-row['merchandise'], row['name'])),
        'from': str(first_day), 'to': str(last_day), 'totals': totals, 'daily': daily,
        'statuses': [dict(row) for row in created_by_status], 'topProducts': ranked[:10],
    }


async def monthly_report(s, month=None, compare=None, shop_id=None):
    month=month if month is not None else today().strftime('%Y-%m')
    selected_days=month_days(month)
    if compare is None:
        check(selected_days[0]>date.min,'INVALID_DATE','Chọn tháng đối chiếu hợp lệ')
        compare=(selected_days[0]-timedelta(days=1)).strftime('%Y-%m')
    comparison_days=month_days(compare)
    daily=await daily_records(s,selected_days+comparison_days,shop_id)
    selected=month_total(month,[daily[str(d)] for d in selected_days])
    reference=month_total(compare,[daily[str(d)] for d in comparison_days])
    return public({'shopId':shop_id,'timezone':'Asia/Ho_Chi_Minh','period':'month','selected':selected,'comparison':reference,
                   'changes':compare_records(selected,reference),'daily':[daily[str(d)] for d in selected_days]})


async def report_scope(s, user, requested=None):
    """Derive seller scope from authentication, never from client claims."""
    from .marketplace import manage_shop
    if user['role'] == 'SELLER' or requested:
        return (await manage_shop(s, user, requested))['id']
    return None
