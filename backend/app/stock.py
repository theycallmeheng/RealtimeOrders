"""Shared warehouse and supplier accounts payable."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert

from .db import T, Fault, add, change, check, now, number, one, rows, text, uid, uuid
from .events import emit

MONEY_MAX = Decimal('999999999999999999')


def whole(value):
    return value.quantize(Decimal('1'), rounding=ROUND_HALF_UP)


async def lock_products(s, ids):
    stock = T['product_stock']
    for product_id in sorted(set(ids)):
        current = await one(s, 'product_stock', stock.c.product_id == product_id, lock=True, required=False)
        if current is None:
            await s.execute(insert(stock).values(product_id=product_id).on_duplicate_key_update(product_id=product_id))


async def position(s, product_id):
    return await one(s, 'product_stock', T['product_stock'].c.product_id == product_id, required=False)


async def movement(s, user, product_id, delta, kind, reference, *, cost=None, reason=''):
    stock = T['product_stock']
    row = await one(s, 'product_stock', stock.c.product_id == product_id, lock=True)
    balance = row['quantity'] + delta
    check(Decimal(0) <= balance <= Decimal('999999999.999'), 'INVALID_STOCK_BALANCE',
          'Số lượng vượt giới hạn kho hoặc không đủ hàng', 409)
    average = row['average_cost']
    if kind == 'OPENING' and delta == 0:
        average = cost
    if delta > 0 and cost is not None:
        check(not row['quantity'] or average is not None, 'COST_REQUIRED', 'Cần kiểm tra lại giá vốn tồn')
        average = ((row['quantity'] * (average or 0) + delta * cost) / balance).quantize(
            Decimal('.000001'), rounding=ROUND_HALF_UP)
    await s.execute(stock.update().where(stock.c.product_id == product_id).values(
        quantity=balance, average_cost=average, opened=True))
    if delta or kind == 'OPENING':
        await add(s, 'stock_ledger', id=uid(), product_id=product_id, actor_id=user['id'], kind=kind,
                  reference_id=reference, delta=delta, balance_after=balance,
                  unit_cost=cost if cost is not None else average, reason=reason, created_at=now())
    return average


async def active_offer_ids(s, product_ids):
    o = T['offers']
    at = now()
    return list((await s.execute(select(o.c.id).where(o.c.product_id.in_(product_ids), o.c.status == 'OPEN',
        o.c.archived_at.is_(None), o.c.opens_at <= at, o.c.closes_at > at))).scalars())


async def publish(s, product_ids):
    from .commerce import catalog_event
    ids = await active_offer_ids(s, product_ids)
    if ids:
        await catalog_event(s, ids)
    emit(s, 'admin:ops', 'STOCK_CHANGED', {})
    from .marketplace import shop_topic, DEFAULT_SHOP
    emit(s, shop_topic(DEFAULT_SHOP), 'STOCK_CHANGED', {})


async def save_supplier(s, user, body, id=None):
    from .commerce import audit, version
    active = body.get('active', True)
    check(isinstance(active, bool), 'INVALID_BOOLEAN', 'Trạng thái không hợp lệ')
    values = dict(name=text(body.get('name'), 150, 1), contact=text(body.get('contact', ''), 200), active=active)
    old = await one(s, 'suppliers', T['suppliers'].c.id == id, lock=True) if id else None
    if old:
        version(old, body)
        await change(s, 'suppliers', id, version=old['version']+1, **values)
    else:
        id = uid()
        await add(s, 'suppliers', id=id, created_at=now(), **values)
    await audit(s, user, 'supplier.save', 'supplier', id, old, values)
    return await one(s, 'suppliers', T['suppliers'].c.id == id)


async def receive(s, user, body):
    from .commerce import audit
    kind = body.get('kind', 'PURCHASE')
    check(kind in ('OPENING', 'PURCHASE'), 'INVALID_RECEIPT_KIND', 'Chọn loại phiếu hợp lệ')
    supplier = None
    if kind == 'PURCHASE':
        supplier = await one(s, 'suppliers', T['suppliers'].c.id == uuid(body.get('supplierId')),
                             T['suppliers'].c.active.is_(True), lock=True)
    try:
        due = date.fromisoformat(body['dueDate']) if body.get('dueDate') else None
    except (ValueError, TypeError):
        check(False, 'INVALID_DATE', 'Hạn thanh toán không hợp lệ')
    lines = body.get('items')
    check(isinstance(lines, list) and 0 < len(lines) <= 100 and all(isinstance(item, dict) for item in lines),
          'INVALID_ITEMS', 'Phiếu cần từ 1 đến 100 sản phẩm')
    ids = [uuid(item.get('productId')) for item in lines]
    check(len(ids) == len(set(ids)), 'DUPLICATE_ITEM', 'Mỗi sản phẩm chỉ xuất hiện một lần')
    await lock_products(s, ids)
    values = []
    errors = []
    for index, (id, item) in enumerate(zip(ids, lines)):
        product = await one(s, 'products', T['products'].c.id == id, T['products'].c.deleted_at.is_(None))
        balance = await position(s, id)
        check(kind != 'OPENING' or not balance['opened'], 'OPENING_EXISTS', 'Sản phẩm đã ghi nhận tồn đầu kỳ hoặc phát sinh kho', 409)
        quantity = cost = None
        try:
            quantity = number(item.get('quantity'), minimum=Decimal(0) if kind == 'OPENING' else Decimal('.001'),
                              maximum=Decimal('999999999.999'))
            check(quantity % product['quantity_step'] == 0, 'INVALID_STEP', 'Số lượng không đúng bước đơn vị')
        except Fault as fault:
            errors.append({'index':index,'productId':id,'name':product['name'],'field':'quantity','message':fault.message})
        try:
            cost = number(item.get('unitCost'), places=0, maximum=MONEY_MAX)
        except Fault as fault:
            errors.append({'index':index,'productId':id,'name':product['name'],'field':'unitCost','message':fault.message})
        if quantity is None or cost is None or any(e['index']==index for e in errors):
            continue
        values.append(dict(product_id=id, quantity=quantity, unit_cost=cost, line_total=whole(quantity*cost)))
    if errors:
        raise Fault('INVALID_RECEIPT_LINES', 'Kiểm tra số lượng và giá nhập: ' + '; '.join(
            e['name'] + ': ' + e['message'] for e in errors), 400, {'lines':errors})
    total = sum(line['line_total'] for line in values)
    check(total <= MONEY_MAX, 'RECEIPT_TOO_LARGE', 'Tổng tiền phiếu vượt giới hạn')
    paid = number(body.get('paidAmount', 0), places=0, maximum=MONEY_MAX)
    check(supplier or paid == 0, 'INVALID_PAYABLE', 'Phiếu kiểm kê không ghi nhận tiền trả trước')
    check(paid <= total, 'PAYMENT_EXCEEDS_RECEIPT', 'Tiền trả trước không được lớn hơn tổng tiền nhập')
    id = uid()
    note = text(body.get('note', ''), 500)
    receipt = await add(s, 'stock_receipts', id=id, supplier_id=supplier['id'] if supplier else None,
        actor_id=user['id'], kind=kind, invoice_number=text(body.get('invoiceNumber', ''), 100),
        due_date=due if supplier else None, total=total, note=note, confirmed_at=now())
    for line in values:
        await add(s, 'stock_receipt_items', receipt_id=id, **line)
        await movement(s, user, line['product_id'], line['quantity'], kind, id, cost=line['unit_cost'], reason=note)
    if paid:
        await record_supplier_payment(s, user, id, paid, 'Trả trước khi nhập kho')
    await audit(s, user, 'stock.receive', 'stock_receipt', id, None, {'kind':kind,'total':total,'paidAmount':paid})
    await publish(s, ids)
    return {**receipt, 'paid':paid, 'outstanding':total-paid if supplier else 0}


async def payment(s, user, id, body):
    receipt = await one(s, 'stock_receipts', T['stock_receipts'].c.id == id, lock=True)
    check(receipt['supplier_id'], 'INVALID_PAYABLE', 'Phiếu kiểm kê không có công nợ', 409)
    t = T['supplier_payments']
    reference = text(body.get('reference'), 150, 1)
    amount = number(body.get('amount'), places=0, minimum=Decimal(1), maximum=MONEY_MAX)
    paid = (await s.execute(select(func.coalesce(func.sum(t.c.amount),0)).where(t.c.receipt_id == id))).scalar_one()
    old = await one(s, 'supplier_payments', t.c.receipt_id == id, t.c.reference == reference, required=False)
    check(not old, 'DUPLICATE_PAYMENT', 'Mã tham chiếu thanh toán đã được ghi nhận', 409)
    outstanding = receipt['total'] - paid
    check(amount <= outstanding, 'PAYMENT_EXCEEDS_DEBT', 'Số tiền vượt khoản còn nợ', 409)
    payment = await record_supplier_payment(s,user,id,amount,reference)
    return {**payment, 'paid': paid + amount, 'outstanding': outstanding - amount}


async def record_supplier_payment(s, user, receipt_id, amount, reference):
    from .commerce import audit
    from .marketplace import shop_topic, DEFAULT_SHOP
    row = await add(s, 'supplier_payments', id=uid(), receipt_id=receipt_id, actor_id=user['id'],
                    amount=amount, reference=reference, paid_at=now())
    await audit(s, user, 'supplier.payment', 'stock_receipt', receipt_id, None, {'amount':amount,'reference':reference})
    for topic in ('admin:ops', shop_topic(DEFAULT_SHOP)):
        emit(s, topic, 'SUPPLIER_PAYMENT_CHANGED', {'receiptId':receipt_id})
    return row


async def receipt_list(s, offset, kind=None):
    from .menus import today
    r, p, v = (T[name] for name in ('stock_receipts','supplier_payments','suppliers'))
    totals = select(p.c.receipt_id, func.sum(p.c.amount).label('paid')).group_by(p.c.receipt_id).subquery()
    query = select(r, v.c.name.label('supplier_name'), func.coalesce(totals.c.paid,0).label('paid')).outerjoin(
        v, v.c.id == r.c.supplier_id).outerjoin(totals, totals.c.receipt_id == r.c.id)
    if kind:
        query = query.where(r.c.kind==kind)
    result = [dict(row) for row in (await s.execute(query.order_by(r.c.confirmed_at.desc(),r.c.id.desc()).limit(50).offset(offset))).mappings()]
    for row in result:
        row['outstanding'] = row['total'] - row['paid'] if row['supplier_id'] else 0
        row['overdue'] = bool(row['outstanding'] and row['due_date'] and row['due_date'] < today())
    return result


async def receipt_detail(s, id):
    r = await one(s, 'stock_receipts', T['stock_receipts'].c.id == id)
    items, products = T['stock_receipt_items'], T['products']
    r['items'] = [dict(row) for row in (await s.execute(select(items, products.c.name).join(
        products, products.c.id == items.c.product_id).where(items.c.receipt_id == id))).mappings()]
    r['payments'] = await rows(s, 'supplier_payments', T['supplier_payments'].c.receipt_id == id,
                               limit=1000, order=T['supplier_payments'].c.paid_at)
    p = T['supplier_payments']
    paid = await s.scalar(select(func.coalesce(func.sum(p.c.amount),0)).where(p.c.receipt_id == id))
    r['paid'] = paid
    r['outstanding'] = r['total'] - paid if r['supplier_id'] else 0
    return r


async def payable_summary(s):
    from .menus import today
    r,p = T['stock_receipts'],T['supplier_payments']
    payments = select(p.c.receipt_id,func.sum(p.c.amount).label('paid')).group_by(p.c.receipt_id).subquery()
    paid = func.coalesce(payments.c.paid,0)
    from sqlalchemy import case
    return dict((await s.execute(select(
        func.coalesce(func.sum(r.c.total),0).label('purchased'),
        func.coalesce(func.sum(paid),0).label('paid'),
        func.coalesce(func.sum(r.c.total-paid),0).label('outstanding'),
        func.coalesce(func.sum(case((r.c.due_date<today(),r.c.total-paid),else_=0)),0).label('overdue')
    ).outerjoin(payments,payments.c.receipt_id==r.c.id).where(r.c.supplier_id.is_not(None)))).mappings().one())


async def adjust(s, user, body):
    id = uuid(body.get('productId'))
    await lock_products(s, [id])
    product = await one(s, 'products', T['products'].c.id == id, T['products'].c.deleted_at.is_(None))
    balance = await position(s, id)
    check(balance['opened'] and balance['average_cost'] is not None, 'OPENING_REQUIRED', 'Ghi nhận tồn đầu kỳ hoặc nhập hàng trước', 409)
    delta = number(body.get('delta'), minimum=Decimal('-999999999.999'), maximum=Decimal('999999999.999'))
    check(delta and delta % product['quantity_step'] == 0,'INVALID_STEP','Điều chỉnh phải khác 0 và đúng bước đơn vị')
    reason = text(body.get('reason'),500,1)
    reference = uid()
    await movement(s,user,id,delta,'ADJUSTMENT',reference,reason=reason)
    from .commerce import audit
    await audit(s,user,'stock.adjust','product',id,{'quantity':balance['quantity']},{'delta':delta,'reason':reason})
    await publish(s,[id])
    return await position(s,id)
