"""payOS boundary and append-only receipts. No provider I/O while holding SQL locks."""
import asyncio
import base64
import io
import hashlib
import hmac
import json
import re
from datetime import timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
import httpx
from sqlalchemy import select, func
from .config import settings
from .db import T, Session, now, uid, one, add, change, check, number, public, Fault
from .events import emit, notify, flush_events


def configured():
    return bool(settings.payos_client_id and settings.payos_api_key and settings.payos_checksum_key)


def signature(data):
    def value(v):
        if v is None: return ''
        if isinstance(v, bool): return str(v).lower()
        if isinstance(v, (dict, list)): return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return str(v)
    canonical = '&'.join(f'{k}={value(data[k])}' for k in sorted(data))
    return hmac.new(settings.payos_checksum_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def verified(data, digest):
    return isinstance(data, dict) and isinstance(digest, str) and hmac.compare_digest(signature(data), digest)


async def provider(method, path, payload=None, missing=False):
    check(configured(), 'PAYMENT_NOT_CONFIGURED', 'Thanh toán payOS chưa được cấu hình', 503)
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.request(method, 'https://api-merchant.payos.vn/v2/payment-requests'+path,
                headers={'x-client-id': settings.payos_client_id, 'x-api-key': settings.payos_api_key}, json=payload)
        result = response.json()
        if missing and method == 'GET' and (response.status_code == 404 or str(result.get('code')) in ('101', '231')): return None
        check(response.status_code == 200 and result.get('code') == '00', 'PAYMENT_PROVIDER_ERROR', 'Chưa nhận được kết quả payOS; thử lại cùng đơn để đối soát', 503)
        check(verified(result.get('data'), result.get('signature')), 'PAYMENT_SIGNATURE', 'Kết quả payOS không hợp lệ', 502)
        return result['data']
    except (httpx.HTTPError, ValueError, TypeError):
        raise Fault('PAYMENT_UNAVAILABLE', 'Chưa kết nối được payOS; không tạo lại đơn, hãy thử thanh toán lại', 503)


async def vat_policy(s):
    row = await one(s, 'system_settings', T['system_settings'].c.setting_key == 'vat_policy')
    return row['value_json'], row['version']


def tax(subtotal, rate):
    return (Decimal(subtotal)*number(rate, places=2, maximum=Decimal(100))/100).quantize(Decimal(1), rounding=ROUND_HALF_UP)


async def balance(s, order_id):
    t = T['money_entries']
    data = (await s.execute(select(t.c.kind, func.sum(t.c.amount)).where(t.c.order_id == order_id).group_by(t.c.kind))).all()
    amounts = dict(data)
    return amounts.get('PAYMENT', Decimal(0)), amounts.get('REFUND', Decimal(0))


async def summary(s, order):
    paid, refunded = await balance(s, order['id'])
    return {'received': paid, 'refunded': refunded, 'remaining': Decimal(0) if order['status'] in ('CANCELLED','REJECTED') else max(Decimal(0), order['total']-paid+refunded),
            'tracked': order['payment_method'] != 'LEGACY'}


async def changed(s, order):
    from .marketplace import shop_topic
    payload = {'id': order['id'], 'status': order['status'], 'paymentStatus': order['payment_status'], 'version': str(order['version'])}
    for topic in ('user:'+order['customer_id'], 'admin:ops', shop_topic(order['shop_id'])):
        emit(s, topic, 'ORDER_CHANGED', payload, order['id'], order['version'])
    if order.get('courier_id'): emit(s, 'courier:'+order['courier_id'], 'ORDER_CHANGED', payload, order['id'], order['version'])


async def request_refund(s, order):
    paid, refunded = await balance(s, order['id'])
    target = max(Decimal(0), paid-refunded-(0 if order['status'] in ('CANCELLED', 'REJECTED') else order['total']))
    if target:
        old = await one(s, 'refund_requests', T['refund_requests'].c.order_id == order['id'], required=False, lock=True)
        if old:
            await change(s, 'refund_requests', old['id'], state='PENDING', amount=target, completed_at=None,completed_by=None,reference=None,note='')
        else: await add(s, 'refund_requests', id=uid(), order_id=order['id'], amount=target, state='PENDING', created_at=now())
        await change(s, 'orders', order['id'], payment_status='REFUND_PENDING')
        order['payment_status'] = 'REFUND_PENDING'


def payment_view(request):
    """Expose only checkout data; QR encoding stays on this server."""
    result = {key: request.get(key) for key in (
        'id', 'order_id', 'order_code', 'amount', 'expires_at', 'state',
        'checkout_url', 'account_name', 'account_number', 'bank_bin',
    )}
    result['receiver'] = 'PLATFORM'
    result['qr_image'] = None
    if request.get('qr_code'):
        import qrcode
        from qrcode.image.pil import PilImage
        image = qrcode.make(request['qr_code'], image_factory=PilImage, box_size=6, border=4)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        result['qr_image'] = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
    return public(result)


def validate_remote(request, remote):
    check(isinstance(remote, dict), 'PAYMENT_PROVIDER_ERROR', 'Chưa lấy được thông tin payOS', 502)
    check(str(remote.get('orderCode')) == str(request['order_code']) and
          str(remote.get('amount', '')).isdigit() and Decimal(str(remote['amount'])) == request['amount'],
          'PAYMENT_AMOUNT_MISMATCH', 'Số tiền hoặc mã payOS không khớp đơn', 502)



async def link(user, order_id):
    check(configured(), 'PAYMENT_NOT_CONFIGURED', 'Thanh toán payOS chưa được cấu hình', 503)
    async with Session.begin() as s:
        o = await one(s, 'orders', T['orders'].c.id == order_id, lock=True)
        check(o['customer_id'] == user['id'] and user['role'] == 'CUSTOMER', 'FORBIDDEN', 'Không có quyền thanh toán đơn', 403)
        check(o['status'] == 'APPROVED' and o['payment_method'] == 'PAYOS' and o['payment_status'] == 'UNPAID', 'INVALID_STATE', 'Đơn chưa được duyệt hoặc không còn chờ thanh toán', 409)
        check(o['payment_deadline'] and now() < o['payment_deadline'], 'PAYMENT_EXPIRED', 'Đã hết thời hạn thanh toán', 409)
        check(o['total'] > 0, 'INVALID_PAYMENT', 'Đơn không cần thanh toán', 409)
        req = await one(s, 'payment_requests', T['payment_requests'].c.order_id == order_id, required=False)
        if req and req['checkout_url']: return payment_view(req)
        if not req:
            await add(s, 'payment_requests', id=uid(), order_id=order_id, amount=o['total'], expires_at=o['payment_deadline'], state='CREATING', created_at=now(), updated_at=now())
            req = await one(s, 'payment_requests', T['payment_requests'].c.order_id == order_id)
    # Reusing the same provider orderCode makes recovery after a lost response safe.
    remote = await provider('GET', '/'+str(req['order_code']), missing=True)
    if remote is None:
        payload = {'amount': int(req['amount']), 'cancelUrl': settings.app_origin+'/orders', 'returnUrl': settings.app_origin+'/orders',
                   'description': 'RO'+str(req['order_code'])[-7:], 'orderCode': req['order_code']}
        payload['signature'] = signature(payload)
        payload['expiredAt'] = int(req['expires_at'].replace(tzinfo=timezone.utc).timestamp())
        try: remote = await provider('POST', '', payload)
        except Fault:
            remote = await provider('GET', '/'+str(req['order_code']), missing=True)
            check(remote is not None, 'PAYMENT_UNAVAILABLE', 'Đang đối soát yêu cầu thanh toán; vui lòng thử lại', 503)
    validate_remote(req,remote)
    await reconcile(req,remote)
    checkout = remote.get('checkoutUrl', '')
    link_id=remote.get('paymentLinkId',remote.get('id',''))
    if not checkout and re.fullmatch(r'[0-9a-fA-F]{32}',str(link_id)):
        checkout='https://pay.payos.vn/web/'+link_id
    host = urlsplit(checkout)
    check(host.scheme == 'https' and host.hostname and (host.hostname == 'payos.vn' or host.hostname.endswith('.payos.vn')),
          'PAYMENT_INVALID_LINK', 'Chưa lấy được link thanh toán hợp lệ; kiểm tra trạng thái đơn trước khi thử lại', 502)
    check(int(remote.get('orderCode', -1)) == req['order_code'] and Decimal(str(remote.get('amount', -1))) == req['amount'], 'PAYMENT_AMOUNT_MISMATCH', 'Số tiền payOS không khớp đơn', 502)
    async with Session.begin() as s:
        current = await one(s, 'orders', T['orders'].c.id == order_id, lock=True)
        check(current['status'] == 'APPROVED' and current['payment_status']=='UNPAID' and current['payment_deadline'] > now(), 'PAYMENT_RESOLVED', 'Đã có kết quả thanh toán hoặc đơn đã hết hạn; tải lại đơn', 409)
        await change(s, 'payment_requests', req['id'], checkout_url=checkout, provider_link_id=remote.get('paymentLinkId', remote.get('id')), state='PENDING', updated_at=now(),
                     qr_code=remote.get('qrCode') or None, account_name=remote.get('accountName') or None,
                     account_number=remote.get('accountNumber') or None, bank_bin=remote.get('bin') or None)
        return payment_view(await one(s, 'payment_requests', T['payment_requests'].c.id == req['id']))


async def webhook(s, body):
    check(configured(), 'PAYMENT_NOT_CONFIGURED', 'payOS chưa được cấu hình', 503)
    data = body.get('data')
    check(verified(data, body.get('signature')), 'PAYMENT_SIGNATURE', 'Chữ ký thanh toán không hợp lệ', 400)
    if body.get('code') != '00' or data.get('code') != '00' or body.get('success') is not True: return {'received': True}
    code = number(data.get('orderCode'), places=0, maximum=Decimal('9007199254740991'))
    req = await one(s, 'payment_requests', T['payment_requests'].c.order_code == int(code), required=False)
    # Provider webhook verification sends a signed example not belonging to an order.
    if not req: return {'received': True, 'ignored': True}
    initial = await one(s, 'orders', T['orders'].c.id == req['order_id'])
    # Serialize changes to withdrawable backing funds with withdrawal decisions.
    await one(s, 'shops', T['shops'].c.id == initial['shop_id'], lock=True)
    o = await one(s, 'orders', T['orders'].c.id == req['order_id'], lock=True)
    check(o['payment_method'] == 'PAYOS', 'INVALID_PAYMENT', 'Đơn không dùng payOS', 409)
    check(not req['provider_link_id'] or data.get('paymentLinkId') == req['provider_link_id'], 'PAYMENT_LINK_MISMATCH', 'Sai link thanh toán', 400)
    reference = 'payos:'+str(data.get('reference', ''))
    check(reference != 'payos:' and len(reference) <= 128 and data.get('currency') == 'VND', 'INVALID_PAYMENT', 'Giao dịch thanh toán không hợp lệ', 400)
    amount = number(data.get('amount'), places=0, minimum=Decimal(1), maximum=Decimal('999999999999999999'))
    old = await one(s, 'money_entries', T['money_entries'].c.provider_ref == reference, required=False)
    if old:
        check(old['order_id'] == o['id'] and old['amount'] == amount, 'PAYMENT_CONFLICT', 'Giao dịch bị trùng tham chiếu', 409)
        return {'received': True}
    receipt_id=uid()
    await add(s, 'money_entries', id=receipt_id, order_id=o['id'], kind='PAYMENT', method='PAYOS', amount=amount, provider_ref=reference, created_at=now())
    paid, refunded = await balance(s, o['id'])
    status = 'PAID' if paid-refunded >= o['total'] else 'UNPAID'
    await change(s, 'orders', o['id'], payment_status=status, version=o['version']+1, updated_at=now())
    o.update(payment_status=status, version=o['version']+1)
    await change(s, 'payment_requests', req['id'], state='PAID' if status == 'PAID' else 'PARTIAL', updated_at=now())
    await request_refund(s, o)
    await changed(s, o)
    await notify(s, o['customer_id'], 'PAYMENT_RECEIVED', {'id': o['id'], 'message': 'Đã ghi nhận giao dịch ngân hàng. Xem trạng thái thanh toán của đơn.'}, receipt_id)
    return {'received': True}


async def expire_order(s, order):
    from .commerce import move_stock, catalog_event, audit
    o = await one(s, 'orders', T['orders'].c.id == order['id'], lock=True)
    if o['status'] != 'APPROVED' or o['payment_status'] not in ('UNPAID',): return
    if not o['payment_deadline'] or o['payment_deadline'] > now(): return
    system = await one(s, 'users', T['users'].c.id == o['customer_id'])
    items = (await s.execute(select(T['order_items']).where(T['order_items'].c.order_id == o['id']).order_by(T['order_items'].c.offer_id))).mappings().all()
    for i in items:
        offer = await one(s, 'offers', T['offers'].c.id == i['offer_id'], lock=True)
        await move_stock(s, system, offer, i['quantity'], 'PAYMENT_EXPIRED', o['id'], o['id'])
    await change(s, 'orders', o['id'], status='CANCELLED', cancelled_at=now(), version=o['version']+1, updated_at=now())
    from sqlalchemy import update
    await s.execute(update(T['cancellation_requests']).where(T['cancellation_requests'].c.order_id==o['id'],T['cancellation_requests'].c.state=='OPEN').values(state='ACCEPTED',decision_note='Hệ thống hủy do hết hạn thanh toán',decided_at=now()))
    await add(s, 'order_status_history', id=uid(), order_id=o['id'], actor_id=system['id'], from_status=o['status'], to_status='CANCELLED', order_version=o['version']+1, reason='Hết hạn thanh toán', created_at=now())
    o.update(status='CANCELLED', version=o['version']+1)
    await request_refund(s, o)
    await changed(s, o)
    await notify(s, o['customer_id'], 'PAYMENT_EXPIRED', {'id': o['id'], 'message': 'Đơn đã hết hạn thanh toán và được hoàn kho.'})
    await audit(s, system, 'order.payment-expired', 'order', o['id'])
    await catalog_event(s, [i['offer_id'] for i in items])


async def reconcile(req, remote):
    """Only called with a response authenticated by provider(); retain bank references."""
    if not remote:return
    validate_remote(req, remote)
    if Decimal(str(remote.get('amountPaid',0)))<=0:return
    transactions=remote.get('transactions') or []
    if isinstance(transactions,dict):transactions=list(transactions.values())
    check(isinstance(transactions,list) and transactions,'PAYMENT_RECONCILIATION_REQUIRED','Ngân hàng đã nhận tiền nhưng chưa đủ dữ liệu đối soát; vui lòng chờ hoặc liên hệ cửa hàng',503)
    async with Session.begin() as s:
        for tx in transactions:
            check(isinstance(tx,dict) and tx.get('reference'),'PAYMENT_RECONCILIATION_REQUIRED','Giao dịch chưa có tham chiếu đối soát',503)
            data={'orderCode':req['order_code'],'amount':tx.get('amount'),'reference':tx['reference'],
                  'paymentLinkId':remote.get('id',remote.get('paymentLinkId')),'currency':'VND','code':'00'}
            await webhook(s,{'code':'00','success':True,'data':data,'signature':signature(data)})
        await flush_events(s)


async def expiry_worker():
    while True:
        try:
            skipped=set()
            if configured():
                async with Session() as s:
                    reqs=(await s.execute(select(T['payment_requests']).where(T['payment_requests'].c.state.in_(('CREATING','PENDING','PARTIAL')),
                        T['payment_requests'].c.updated_at<now()-timedelta(seconds=15)).order_by(T['payment_requests'].c.updated_at).limit(5))).mappings().all()
                for req in reqs:
                    try:
                        remote=await provider('GET','/'+str(req['order_code']),missing=True)
                        await reconcile(dict(req),remote)
                        async with Session() as s:
                            o=await one(s,'orders',T['orders'].c.id==req['order_id'])
                        if o['status']=='CANCELLED' and remote and remote.get('status') not in ('PAID','CANCELLED','EXPIRED'):
                            await provider('POST','/'+str(req['order_code'])+'/cancel',{'cancellationReason':'Order cancelled or expired'})
                        async with Session.begin() as s:
                            current=await one(s,'orders',T['orders'].c.id==req['order_id'],lock=True)
                            await change(s,'payment_requests',req['id'],updated_at=now(),state='PAID' if current['payment_status']=='PAID' else
                                'EXPIRED' if current['status']=='CANCELLED' else req['state'])
                    except Fault:skipped.add(req['order_id'])
            async with Session.begin() as s:
                pending = (await s.execute(select(T['orders']).where(T['orders'].c.payment_method == 'PAYOS', T['orders'].c.payment_status == 'UNPAID',
                    T['orders'].c.status == 'APPROVED', T['orders'].c.payment_deadline <= now()).limit(20))).mappings().all()
                for o in pending:
                    if o['id'] not in skipped:await expire_order(s, dict(o))
                await flush_events(s)
        except asyncio.CancelledError: raise
        except Exception:
            import logging
            logging.getLogger(__name__).error('payment_expiry_unavailable')
        await asyncio.sleep(5)
