"""Vietnamese business-day revenue and gross profit; unknown costs stay unknown."""
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import select, or_, and_
from .db import T,check,public
from .menus import bounds,today,VN


async def report(s, day=None, compare=None):
    try:
        day=date.fromisoformat(day) if day else today()
        compare=date.fromisoformat(compare) if compare else day-timedelta(days=1)
    except ValueError: check(False,'INVALID_DATE','Ngày báo cáo không hợp lệ')
    dates=sorted({compare,*(day-timedelta(days=n) for n in range(7))})
    daily=await daily_records(s,dates)
    selected=daily[str(day)];reference=daily[str(compare)]
    changes=compare_records(selected,reference)
    return public({'timezone':'Asia/Ho_Chi_Minh','selected':selected,'comparison':reference,'changes':changes,
                   'daily':[daily[str(day-timedelta(days=n))] for n in reversed(range(7))]})


async def daily_records(s, dates):
    dates=sorted(set(dates))
    daily={str(d):{'day':str(d),'orders':0,'merchandise':Decimal(0),'shipping':Decimal(0),
                   'cost':Decimal(0),'grossProfit':Decimal(0),'missingCostLines':0} for d in dates}
    o,i=T['orders'],T['order_items']
    # Query only requested contiguous windows, even for distant comparison dates.
    windows=[]
    for d in dates:
        if windows and d==windows[-1][1]+timedelta(days=1): windows[-1]=(windows[-1][0],d)
        else: windows.append((d,d))
    intervals=[and_(o.c.delivered_at>=bounds(a)[0],o.c.delivered_at<bounds(b)[1]) for a,b in windows]
    orders=(await s.execute(select(o.c.id,o.c.delivered_at,o.c.merchandise_total,o.c.shipping_fee)
        .where(o.c.status=='DELIVERED',or_(*intervals)))).mappings().all()
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
    return daily


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


def month_total(month, records):
    result={'month':month}
    for field in ('orders','merchandise','shipping','missingCostLines'):
        result[field]=sum(r[field] for r in records)
    result['cost']=None if result['missingCostLines'] else sum(r['cost'] for r in records)
    result['grossProfit']=None if result['cost'] is None else result['merchandise']-result['cost']
    return result


async def monthly_report(s, month=None, compare=None):
    month=month if month is not None else today().strftime('%Y-%m')
    selected_days=month_days(month)
    if compare is None:
        check(selected_days[0]>date.min,'INVALID_DATE','Chọn tháng đối chiếu hợp lệ')
        compare=(selected_days[0]-timedelta(days=1)).strftime('%Y-%m')
    comparison_days=month_days(compare)
    daily=await daily_records(s,selected_days+comparison_days)
    selected=month_total(month,[daily[str(d)] for d in selected_days])
    reference=month_total(compare,[daily[str(d)] for d in comparison_days])
    return public({'timezone':'Asia/Ho_Chi_Minh','period':'month','selected':selected,'comparison':reference,
                   'changes':compare_records(selected,reference),'daily':[daily[str(d)] for d in selected_days]})
