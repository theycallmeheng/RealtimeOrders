"""Shop-scoped demand tracking; never creates orders, quotes, or reservations."""
import hashlib
import unicodedata
from decimal import Decimal
from urllib.parse import urlsplit
from sqlalchemy import select, func, or_
from .db import T, add, change, check, now, number, one, public, text, uid, uuid
from .commerce import audit, lock_user, version
from .events import emit, notify
from .marketplace import assert_owner, get_shop, shop_topic
from .menus import bounds, today

ACTIVE = ('PENDING', 'REVIEWING', 'WAITING')
LABELS = {'PENDING': 'Chờ tiếp nhận', 'REVIEWING': 'Đang xem xét', 'WAITING': 'Chờ mở bán',
          'OPENED': 'Đã mở bán', 'REJECTED': 'Từ chối', 'CANCELLED': 'Khách đã hủy'}


def customer_only(user):
    check(user['role'] == 'CUSTOMER', 'FORBIDDEN', 'Chức năng dành cho khách hàng', 403)


def safe_url(value):
    value = text(value, 2048)
    if value:
        try:
            parsed = urlsplit(value)
            check(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                  and not any(c.isspace() or ord(c) < 32 for c in value),
                  'INVALID_URL', 'Ảnh và liên kết tham khảo phải là URL HTTPS hợp lệ')
            parsed.port
        except ValueError:
            check(False, 'INVALID_URL', 'URL không hợp lệ')
    return value


async def fields(s, user, body):
    from .moderation import sanitize
    name = await sanitize(s, user, text(body.get('name'), 200, 1), 'product_request')
    normalized = ' '.join(unicodedata.normalize('NFC', name).casefold().split())
    return dict(name=name, name_key=hashlib.sha256(normalized.encode()).hexdigest(),
        description=await sanitize(s, user, text(body.get('description'), 2000, 1), 'product_request'),
        quantity=number(body.get('quantity'), minimum=Decimal('.001')),
        unit_label=text(body.get('unit'), 40, 1), image_url=safe_url(body.get('imageUrl', '')),
        reference_url=safe_url(body.get('referenceUrl', '')),
        desired_price=None if body.get('desiredPrice') in (None, '') else number(body['desiredPrice'], places=0))


def entry(user, status, note):
    return public({'status': status, 'note': note, 'actorId': user['id'] if user else None, 'at': now()})


async def duplicate(s, user, shop_id, key, exclude=None):
    t = T['product_requests']
    conditions = [t.c.customer_id == user['id'], t.c.shop_id == shop_id,
                  t.c.name_key == key, t.c.status.in_(ACTIVE)]
    if exclude: conditions.append(t.c.id != exclude)
    check(not await one(s, 'product_requests', *conditions, required=False), 'REQUEST_DUPLICATE',
          'Bạn đã có yêu cầu cùng tên sản phẩm đang được xử lý tại shop này', 409)


async def detail(s, user, id):
    row = await one(s, 'product_requests', T['product_requests'].c.id == id)
    if user['role'] == 'CUSTOMER':
        check(row['customer_id'] == user['id'], 'FORBIDDEN', 'Yêu cầu không thuộc tài khoản này', 403)
    else: assert_owner(user, row['shop_id'])
    shop = await get_shop(s, row['shop_id'])
    customer = await one(s, 'users', T['users'].c.id == row['customer_id'])
    row.pop('name_key', None)
    row.update(shop_name=shop['name'], customer_name=customer['display_name'])
    # Do not expose another customer's phone/email or product cost through this API.
    return row


async def listing(s, user, params):
    t, u, shops = T['product_requests'], T['users'], T['shops']
    conditions = [t.c.customer_id == user['id']] if user['role'] == 'CUSTOMER' else []
    if params.get('status'):
        check(params['status'] in LABELS, 'INVALID_STATE', 'Trạng thái không hợp lệ')
        conditions.append(t.c.status == params['status'])
    try: offset = int(params.get('offset', 0))
    except (ValueError, TypeError): offset = -1
    check(0 <= offset <= 100000, 'INVALID_PAGE', 'Trang không hợp lệ')
    result = [dict(r) for r in (await s.execute(select(t, u.c.display_name.label('customer_name'), shops.c.name.label('shop_name'))
        .join(u, t.c.customer_id == u.c.id).join(shops, t.c.shop_id == shops.c.id).where(*conditions)
        .order_by(t.c.created_at.desc(), t.c.id.desc()).offset(offset).limit(50))).mappings()]
    for row in result: row.pop('name_key', None)
    return result


def changed(s, row):
    payload = {'id': row['id']}
    for topic in ('user:' + row['customer_id'], shop_topic(row['shop_id']), 'admin:ops'):
        emit(s, topic, 'PRODUCT_REQUEST_CHANGED', payload)


async def create(s, user, body):
    customer_only(user)
    await lock_user(s, user['id'])  # Serializes the daily quota and duplicate-name check.
    from .marketplace import DEFAULT_SHOP
    shop = await get_shop(s, DEFAULT_SHOP, active=True)
    t = T['product_requests']; start, end = bounds(today())
    count = await s.scalar(select(func.count()).select_from(t).where(
        t.c.customer_id == user['id'], t.c.created_at >= start, t.c.created_at < end))
    check(count < 5, 'REQUEST_LIMIT', 'Bạn chỉ được gửi tối đa 5 yêu cầu mỗi ngày', 429)
    data = await fields(s, user, body)
    await duplicate(s, user, shop['id'], data['name_key'])
    row = await add(s, 'product_requests', id=uid(), customer_id=user['id'], shop_id=shop['id'],
        **data, status='PENDING', history=[entry(user, 'PENDING', 'Khách gửi yêu cầu')],
        version=1, created_at=now(), updated_at=now())
    changed(s, row)
    owners = (await s.execute(select(T['users'].c.id).where(T['users'].c.shop_id == shop['id'],
        T['users'].c.role == 'SELLER', T['users'].c.status == 'ACTIVE'))).scalars().all()
    for id in owners:
        await notify(s, id, 'PRODUCT_REQUEST_NEW', {'requestId': row['id'], 'message': 'Có yêu cầu sản phẩm mới: ' + data['name']})
    await audit(s, user, 'product_request.create', 'product_request', row['id'], None, {'status': 'PENDING'})
    return await detail(s, user, row['id'])


async def customer_edit(s, user, id, body, cancel=False):
    customer_only(user)
    await lock_user(s, user['id'])
    row = await one(s, 'product_requests', T['product_requests'].c.id == id, lock=True)
    check(row['customer_id'] == user['id'], 'FORBIDDEN', 'Yêu cầu không thuộc tài khoản này', 403)
    version(row, body)
    check(row['status'] in ACTIVE if cancel else row['status'] == 'PENDING', 'INVALID_STATE',
          'Chỉ được sửa khi chờ tiếp nhận; chỉ được hủy trước khi mở bán hoặc bị từ chối', 409)
    data = {'status': 'CANCELLED'} if cancel else await fields(s, user, body)
    if not cancel: await duplicate(s, user, row['shop_id'], data['name_key'], id)
    note = 'Khách hủy yêu cầu' if cancel else 'Khách sửa nội dung'
    await change(s, 'product_requests', id, **data, version=row['version']+1, updated_at=now(),
                 history=row['history']+[entry(user, data.get('status', row['status']), note)])
    changed(s, row)
    await audit(s, user, 'product_request.cancel' if cancel else 'product_request.edit', 'product_request', id)
    if cancel:
        await notify(s, user['id'], 'PRODUCT_REQUEST_STATUS', {'requestId': id, 'message': LABELS['CANCELLED'] + ': ' + row['name']})
    return await detail(s, user, id)


async def review(s, user, id, body):
    initial = await one(s, 'product_requests', T['product_requests'].c.id == id)
    assert_owner(user, initial['shop_id'])
    await lock_user(s, initial['customer_id'])
    row = await one(s, 'product_requests', T['product_requests'].c.id == id, lock=True)
    assert_owner(user, row['shop_id']); version(row, body)
    target = body.get('status')
    transitions = {'PENDING': ('REVIEWING', 'REJECTED'), 'REVIEWING': ('WAITING', 'REJECTED'), 'WAITING': ('WAITING', 'REJECTED')}
    check(target in transitions.get(row['status'], ()), 'INVALID_STATE', 'Không thể chuyển trạng thái yêu cầu', 409)
    note = text(body.get('note', ''), 1000, 1 if target == 'REJECTED' else 0)
    values = {'status': target, 'decision_note': note}
    if target == 'WAITING':
        product = await one(s, 'products', T['products'].c.id == uuid(body.get('productId')),
                            T['products'].c.shop_id == row['shop_id'], T['products'].c.deleted_at.is_(None),
                            T['products'].c.active.is_(True))
        customer = await one(s, 'users', T['users'].c.id == row['customer_id'])
        check(product['allowed_group_ids'] is None or customer['group_id'] in product['allowed_group_ids'],
              'GROUP_RESTRICTED', 'Sản phẩm không dành cho nhóm của khách yêu cầu', 409)
        values['product_id'] = product['id']
    await change(s, 'product_requests', id, **values, version=row['version']+1, updated_at=now(),
                 history=row['history']+[entry(user, target, note)])
    changed(s, row)
    await notify(s, row['customer_id'], 'PRODUCT_REQUEST_STATUS',
        {'requestId': id, 'message': LABELS[target] + ': ' + row['name'] + ('. ' + note if note else '')})
    await audit(s, user, 'product_request.review', 'product_request', id, {'status': row['status']}, values)
    if target == 'WAITING': await opened_batch(s, id)
    return await detail(s, user, id)


async def opened_batch(s, request_id=None):
    """Complete only purchasable requests, including scheduled opens and restocks.

    Candidate queries do not lock catalog rows. Lock request rows with SKIP LOCKED
    so a customer cancellation or seller update cannot be overwritten.
    """
    t, o, p, m, u, price, groups, shops = (T[name] for name in (
        'product_requests', 'offers', 'products', 'daily_menus', 'users', 'offer_prices', 'customer_groups', 'shops'))
    def allowed(column):
        return or_(column.is_(None), func.json_type(column) == 'NULL', func.json_contains(column, func.json_quote(u.c.group_id)) == 1)
    conditions = [t.c.status == 'WAITING', o.c.status == 'OPEN', o.c.archived_at.is_(None),
        o.c.available_qty >= p.c.quantity_step, T['product_stock'].c.quantity>=p.c.quantity_step,
        p.c.active.is_(True), p.c.deleted_at.is_(None),
        m.c.status == 'OPEN', m.c.opens_at <= now(), m.c.closes_at > now(),
        shops.c.active.is_(True), u.c.status == 'ACTIVE', groups.c.active.is_(True),
        allowed(p.c.allowed_group_ids), allowed(o.c.allowed_group_ids), allowed(m.c.allowed_group_ids)]
    if request_id: conditions.append(t.c.id == request_id)
    eligible = (select(t.c.id, t.c.customer_id, o.c.id.label('offer_id'))
        .join(o, o.c.product_id == t.c.product_id).join(p, p.c.id == o.c.product_id)
        .join(T['product_stock'], T['product_stock'].c.product_id == p.c.id)
        .join(m, m.c.id == o.c.menu_id).join(u, u.c.id == t.c.customer_id)
        .join(price, (price.c.offer_id == o.c.id) & (price.c.group_id == u.c.group_id))
        .join(groups, groups.c.id == u.c.group_id).join(shops, shops.c.id == t.c.shop_id)
        .where(*conditions))
    candidates = (await s.execute(eligible.order_by(t.c.created_at).limit(100))).mappings().all()
    for candidate in candidates:
        # Match customer editing's user -> request lock order, including the
        # notification FK, and skip busy customers until the next monitor tick.
        owner = (await s.execute(select(u.c.id).where(u.c.id == candidate['customer_id'])
            .with_for_update(skip_locked=True))).first()
        if not owner: continue
        row = (await s.execute(select(t).where(t.c.id == candidate['id'], t.c.status == 'WAITING')
            .with_for_update(skip_locked=True))).mappings().first()
        if not row: continue
        row = dict(row)
        # A seller may have relinked WAITING to a different product between
        # candidate selection and locking. Recheck against the locked request.
        if not (await s.execute(eligible.where(t.c.id == row['id'], o.c.id == candidate['offer_id']).limit(1))).first():
            continue
        await change(s, 'product_requests', row['id'], status='OPENED', offer_id=candidate['offer_id'],
            version=row['version']+1, updated_at=now(), history=row['history']+[entry(None, 'OPENED', 'Sản phẩm đã mở bán cho khách')])
        changed(s, row)
        await notify(s, row['customer_id'], 'PRODUCT_REQUEST_OPENED', {'requestId': row['id'],
            'offerId': candidate['offer_id'], 'shopId': row['shop_id'], 'message': 'Sản phẩm bạn yêu cầu đã mở bán: ' + row['name']})
