"""Vietnamese business-day revenue and gross profit; unknown costs stay unknown."""
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import select
from .db import T,check,public
from .menus import bounds,today,VN


async def report(s, day=None, compare=None):
    try:
        day=date.fromisoformat(day) if day else today()
        compare=date.fromisoformat(compare) if compare else day-timedelta(days=1)
    except ValueError: check(False,'INVALID_DATE','Ngày báo cáo không hợp lệ')
    dates=sorted({compare,*(day-timedelta(days=n) for n in range(7))})
    daily={str(d):{'day':str(d),'orders':0,'merchandise':Decimal(0),'shipping':Decimal(0),
                   'cost':Decimal(0),'grossProfit':Decimal(0),'missingCostLines':0} for d in dates}
    o,i=T['orders'],T['order_items']
    start=bounds(dates[0])[0];end=bounds(dates[-1])[1]
    orders=(await s.execute(select(o.c.id,o.c.delivered_at,o.c.merchandise_total,o.c.shipping_fee)
        .where(o.c.status=='DELIVERED',o.c.delivered_at>=start,o.c.delivered_at<end))).mappings().all()
    by_id={row['id']:str((row['delivered_at']+VN).date()) for row in orders}
    for row in orders:
        record=daily.get(by_id[row['id']])
        if record is not None:
            record['orders']+=1;record['merchandise']+=row['merchandise_total'];record['shipping']+=row['shipping_fee']
    if by_id:
        for item in (await s.execute(select(i).where(i.c.order_id.in_(by_id)))).mappings():
            record=daily.get(by_id[item['order_id']])
            if record is None: continue
            if item['cost_price_snapshot'] is None: record['missingCostLines']+=1
            else: record['cost']+=(item['quantity']*item['cost_price_snapshot']).quantize(Decimal(1),rounding=ROUND_HALF_UP)
    for record in daily.values():
        if record['missingCostLines']:record['cost']=None;record['grossProfit']=None
        else: record['grossProfit']=record['merchandise']-record['cost']
    selected=daily[str(day)];reference=daily[str(compare)]
    changes={}
    for field in ('merchandise','grossProfit','orders'):
        a,b=selected[field],reference[field]
        changes[field]={'amount':None if a is None or b is None else a-b,
            'percent':None if a is None or b in (None,0) else ((Decimal(a)-Decimal(b))*100/abs(Decimal(b))).quantize(Decimal('.01'))}
    return public({'timezone':'Asia/Ho_Chi_Minh','selected':selected,'comparison':reference,'changes':changes,
                   'daily':[daily[str(day-timedelta(days=n))] for n in reversed(range(7))]})
