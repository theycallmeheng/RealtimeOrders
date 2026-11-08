"""Shop ownership, onboarding, and balances backed by received order payments."""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import case, func, select, update
from . import auth
from .db import T, add, change, check, now, number, one, rows, text, uid, uuid
from .events import emit, notify
from .menus import today

DEFAULT_SHOP = '00000000-0000-4000-8000-000000000001'
MINIMUM_BALANCE = Decimal(1000000)
MONTHLY_LIMIT = 2
PUBLIC_PROFILE_FIELDS = ('description', 'address', 'phone', 'logoUrl', 'coverUrl')


def shop_topic(shop_id):
    return 'shop:' + shop_id + ':ops'


def assert_owner(user, shop_id):
    check(user['role'] == 'ADMIN' or (
        user['role'] == 'SELLER' and user.get('shop_id') == shop_id
    ), 'FORBIDDEN', 'Dữ liệu thuộc shop khác', 403)


def scope(table, user, shop_id=None):
    if user['role'] == 'SELLER':
        check(user.get('shop_id'), 'SHOP_REQUIRED', 'Tài khoản chưa thuộc shop', 403)
        if shop_id:
            assert_owner(user, shop_id)
        return [table.c.shop_id == user['shop_id']]
    return [table.c.shop_id == uuid(shop_id)] if shop_id else []


async def get_shop(s, shop_id, active=False, lock=False):
    table = T['shops']
    conditions = [table.c.id == shop_id]
    if active:
        conditions.append(table.c.active.is_(True))
    return await one(s, 'shops', *conditions, lock=lock)


async def manage_shop(s, user, requested=None, lock=False):
    auth.require_shop(user)
    shop_id = uuid(requested) if requested else user.get('shop_id') if user['role'] == 'SELLER' else DEFAULT_SHOP
    check(shop_id, 'SHOP_REQUIRED', 'Tài khoản chưa thuộc shop', 403)
    assert_owner(user, shop_id)
    return await get_shop(s, shop_id, lock=lock)


def public_shop(shop):
    profile = shop['profile_json']
    return {'id': shop['id'], 'name': shop['name'], 'active': shop['active'],
            **{field: profile.get(field, '') for field in PUBLIC_PROFILE_FIELDS}}


async def list_shops(s, include_inactive=False):
    table = T['shops']
    conditions = [] if include_inactive else [table.c.active.is_(True)]
    return [public_shop(row) for row in await rows(s, 'shops', *conditions, order=table.c.name, limit=500)]


async def my_application(s, user):
    return await one(s, 'shop_applications', T['shop_applications'].c.applicant_id == user['id'], required=False)


async def apply(s, user, body):
    from .commerce import audit, lock_user
    current = await lock_user(s, user['id'])
    check(current['role'] == 'CUSTOMER' and not current['shop_id'], 'FORBIDDEN', 'Tài khoản đã thuộc một shop', 403)
    previous = await my_application(s, current)
    check(not previous or previous['status'] == 'REJECTED', 'APPLICATION_EXISTS', 'Hồ sơ đã được gửi', 409)
    profile = {
        'name': text(body.get('name'), 200, 1),
        'address': text(body.get('address'), 200, 1),
        'description': text(body.get('description', ''), 2000),
        'phone': current['phone_e164'],
    }
    values = dict(profile_json=profile, status='PENDING', decision_note='', reviewed_by=None, updated_at=now())
    if previous:
        id = previous['id']
        await change(s, 'shop_applications', id, version=previous['version']+1, **values)
    else:
        id = uid()
        await add(s, 'shop_applications', id=id, applicant_id=current['id'], created_at=now(), **values)
    await audit(s, user, 'shop.apply', 'shop_application', id, None, {'name': profile['name']})
    emit(s, 'admin:ops', 'SHOP_CHANGED', {'refresh': True})
    return await my_application(s, current)


async def review_application(s, user, id, body):
    from .commerce import audit, lock_user, version
    auth.require_admin(user)
    table = T['shop_applications']
    application = await one(s, 'shop_applications', table.c.id == id)
    owner = await lock_user(s, application['applicant_id'])
    application = await one(s, 'shop_applications', table.c.id == id, lock=True)
    version(application, body)
    check(application['status'] == 'PENDING', 'INVALID_STATE', 'Hồ sơ đã được xử lý', 409)
    approved = body.get('approved')
    check(isinstance(approved, bool), 'INVALID_BOOLEAN', 'Chọn duyệt hoặc từ chối')
    note = text(body.get('note', ''), 500, 0 if approved else 1)
    shop_id = None
    if approved:
        check(owner['role'] == 'CUSTOMER' and owner['status'] == 'ACTIVE' and not owner['shop_id'],
              'INVALID_ACCOUNT', 'Tài khoản đăng ký không đủ điều kiện', 409)
        shop_id = uid()
        profile = application['profile_json']
        await add(s, 'shops', id=shop_id, name=profile['name'], profile_json=profile, created_at=now(), updated_at=now())
        await change(s, 'users', owner['id'], role='SELLER', shop_id=shop_id,
                     version=owner['version']+1, security_version=owner['security_version']+1, updated_at=now())
        await s.execute(update(T['sessions']).where(T['sessions'].c.user_id == owner['id'],
                                                  T['sessions'].c.revoked_at.is_(None)).values(revoked_at=now()))
        emit(s, 'user:'+owner['id'], 'SESSION_REVOKED', {'message': 'Shop đã được duyệt. Đăng nhập lại để vào kênh người bán.'})
    status = 'APPROVED' if approved else 'REJECTED'
    await change(s, 'shop_applications', id, shop_id=shop_id, status=status, decision_note=note,
                 reviewed_by=user['id'], version=application['version']+1, updated_at=now())
    await audit(s, user, 'shop.review', 'shop_application', id, None, {'status': status, 'shopId': shop_id, 'note': note})
    await notify(s, owner['id'], 'SHOP_APPLICATION', {'message': 'Shop đã được duyệt.' if approved else 'Hồ sơ shop cần bổ sung: '+note})
    emit(s, 'admin:ops', 'SHOP_CHANGED', {'refresh': True})
    if approved:
        for group in await rows(s, 'customer_groups', T['customer_groups'].c.active.is_(True)):
            emit(s, 'catalog:'+group['id'], 'SHOP_CHANGED', {'refresh': True})
    return await one(s, 'shop_applications', table.c.id == id)


async def fee_policy(s):
    table = T['system_settings']
    setting = await one(s, 'system_settings', table.c.setting_key == 'platform_fee', required=False)
    return {'rate': setting['value_json']['rate'] if setting else '10', 'version': str(setting['version']) if setting else '0'}


async def save_fee(s, user, body):
    from .commerce import audit
    auth.require_admin(user)
    table = T['system_settings']
    setting = await one(s, 'system_settings', table.c.setting_key == 'platform_fee', lock=True, required=False)
    version = setting['version'] if setting else 0
    check(str(version) == str(body.get('expectedVersion')), 'VERSION_CONFLICT', 'Mức phí đã đổi', 409)
    rate = number(body.get('rate'), places=2, maximum=Decimal(100))
    values = dict(value_json={'rate': str(rate)}, version=version+1, updated_at=now(), updated_by=user['id'])
    if setting:
        await s.execute(update(table).where(table.c.setting_key == 'platform_fee').values(**values))
    else:
        await add(s, 'system_settings', setting_key='platform_fee', **values)
    await audit(s, user, 'shop.fee', 'settings', None, None, {'rate': rate})
    return await fee_policy(s)


async def order_fee(s, subtotal):
    rate = Decimal((await fee_policy(s))['rate'])
    return rate, (subtotal * rate / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def eligible_orders(shop_id, completed=True):
    o, m, r = T['orders'], T['money_entries'], T['refund_requests']
    # Only platform receipts and COD already handed to the platform fund withdrawals.
    received = select(func.coalesce(func.sum(case(
        (m.c.kind == 'REFUND', -m.c.amount),
        ((m.c.method != 'COD') | m.c.remitted_at.is_not(None), m.c.amount),
        else_=0,
    )), 0)).where(m.c.order_id == o.c.id).scalar_subquery()
    pending_refund = select(r.c.id).where(r.c.order_id == o.c.id, r.c.state == 'PENDING').exists()
    return [o.c.shop_id == shop_id, (o.c.status == 'DELIVERED' if completed else o.c.status.in_(('APPROVED','PREPARING','SHIPPING','READY_FOR_PICKUP','DELIVERY_FAILED'))), o.c.payment_status == 'PAID',
            o.c.platform_fee_rate.is_not(None), received >= o.c.total, ~pending_refund]


async def balance(s, shop_id):
    o, w = T['orders'], T['shop_withdrawals']
    totals = (await s.execute(select(
        func.coalesce(func.sum(o.c.merchandise_total - o.c.platform_fee), 0),
        func.coalesce(func.sum(o.c.platform_fee), 0),
    ).where(*eligible_orders(shop_id)))).one()
    held = (await s.execute(select(func.coalesce(func.sum(o.c.merchandise_total - o.c.platform_fee), 0))
                            .where(*eligible_orders(shop_id, completed=False)))).scalar_one()
    withdrawals = dict((await s.execute(select(w.c.status, func.sum(w.c.amount))
                        .where(w.c.shop_id == shop_id).group_by(w.c.status))).all())
    month = today().replace(day=1)
    used = (await s.execute(select(func.count()).select_from(w).where(
        w.c.shop_id == shop_id, w.c.period_month == month, w.c.status != 'REJECTED',
    ))).scalar_one()
    pending, paid = withdrawals.get('PENDING', Decimal(0)), withdrawals.get('PAID', Decimal(0))
    available = max(Decimal(0), totals[0] - pending - paid)
    return {'available': available, 'held': held, 'pending': pending, 'paid': paid, 'fees': totals[1],
            'month': month, 'used': used, 'limit': MONTHLY_LIMIT, 'minimumBalance': MINIMUM_BALANCE}


async def save_bank(s, user, body):
    import re
    from .commerce import audit
    check(user['role'] == 'SELLER', 'FORBIDDEN', 'Chỉ chủ shop sửa tài khoản nhận tiền', 403)
    shop = await manage_shop(s, user, lock=True)
    account = text(body.get('accountNumber'), 30, 6)
    check(re.fullmatch(r'[0-9]{6,30}', account) is not None, 'INVALID_BANK_ACCOUNT', 'Số tài khoản chỉ gồm chữ số')
    bank = {'bankName': text(body.get('bankName'), 100, 1),
            'accountHolder': text(body.get('accountHolder'), 100, 1), 'accountNumber': account}
    await change(s, 'shops', shop['id'], payout_json=bank, updated_at=now())
    await audit(s, user, 'shop.bank', 'shop', shop['id'], None, {'bankName': bank['bankName']})
    return bank


async def withdraw(s, user, body):
    from .commerce import audit
    check(user['role'] == 'SELLER', 'FORBIDDEN', 'Chỉ shop gửi yêu cầu rút tiền', 403)
    shop = await manage_shop(s, user, lock=True)
    check(shop['payout_json'], 'BANK_REQUIRED', 'Thêm tài khoản ngân hàng nhận tiền', 409)
    totals = await balance(s, shop['id'])
    check(totals['used'] < MONTHLY_LIMIT, 'WITHDRAWAL_LIMIT', 'Đã dùng hết hai lượt rút của tháng', 409)
    check(totals['available'] >= MINIMUM_BALANCE, 'BALANCE_MINIMUM', 'Số dư khả dụng cần đạt 1.000.000 đ', 409)
    amount = number(body.get('amount'), places=0, minimum=Decimal(1), maximum=totals['available'])
    row = await add(s, 'shop_withdrawals', id=uid(), shop_id=shop['id'], requested_by=user['id'], amount=amount,
                    period_month=totals['month'], bank_snapshot=shop['payout_json'], created_at=now())
    await audit(s, user, 'shop.withdraw', 'withdrawal', row['id'], None, {'amount': amount, 'shopId': shop['id']})
    emit(s, 'admin:ops', 'MONEY_CHANGED', {'refresh': True})
    emit(s, shop_topic(shop['id']), 'MONEY_CHANGED', {'refresh': True})
    return await one(s, 'shop_withdrawals', T['shop_withdrawals'].c.id == row['id'])


async def decide_withdrawal(s, user, id, body):
    from .commerce import audit, version
    auth.require_admin(user)
    table = T['shop_withdrawals']
    row = await one(s, 'shop_withdrawals', table.c.id == id)
    await get_shop(s, row['shop_id'], lock=True)
    row = await one(s, 'shop_withdrawals', table.c.id == id, lock=True)
    version(row, body)
    check(row['status'] == 'PENDING', 'INVALID_STATE', 'Yêu cầu đã được xử lý', 409)
    status = body.get('status')
    check(status in ('PAID', 'REJECTED'), 'INVALID_STATUS', 'Chọn xác nhận đã chi hoặc từ chối')
    if status == 'PAID':
        # Recheck backing funds under the same shop lock as withdrawal creation.
        # Receipts may have become ineligible while this request was pending.
        orders = T['orders']
        funded = (await s.execute(select(func.coalesce(func.sum(orders.c.merchandise_total - orders.c.platform_fee), 0))
                                 .where(*eligible_orders(row['shop_id'])))).scalar_one()
        reserved = (await s.execute(select(func.coalesce(func.sum(table.c.amount), 0)).where(
            table.c.shop_id == row['shop_id'], table.c.id != id, table.c.status.in_(('PENDING', 'PAID')),
        ))).scalar_one()
        check(funded - reserved >= row['amount'], 'INSUFFICIENT_SETTLED_BALANCE',
              'Tiền đã đối soát không đủ để chi trả yêu cầu này; kiểm tra hoàn tiền và các khoản đang chờ rút', 409)
    reference = text(body.get('reference', ''), 128, 1) if status == 'PAID' else None
    note = text(body.get('note', ''), 500, 1 if status == 'REJECTED' else 0)
    await change(s, 'shop_withdrawals', id, status=status, bank_reference=reference, decision_note=note,
                 decided_by=user['id'], decided_at=now(), version=row['version']+1)
    await audit(s, user, 'shop.withdrawal.decide', 'withdrawal', id, None,
                {'shopId': row['shop_id'], 'amount': row['amount'], 'status': status, 'reference': reference})
    emit(s, 'admin:ops', 'MONEY_CHANGED', {'refresh': True})
    emit(s, shop_topic(row['shop_id']), 'MONEY_CHANGED', {'refresh': True})
    await notify(s, row['requested_by'], 'SHOP_WITHDRAWAL', {'message': 'Yêu cầu rút đã được chi trả.' if status == 'PAID' else 'Yêu cầu rút bị từ chối: '+note})
    return await one(s, 'shop_withdrawals', table.c.id == id)
