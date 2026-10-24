import asyncio
import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert
from .config import settings
from .db import T, Session, now, uid, one, add, change, check, text, Fault

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = hasher.hash(secrets.token_hex(16))

def hashed(value):
    return hashlib.sha256(value.encode()).digest()

def secret_hmac(value):
    return hmac.digest(settings.app_secret.encode(), value.encode(), 'sha256')

def phone(value):
    value = re.sub(r'[\s().-]', '', text(value, 24, 9))
    if value.startswith('0'): value = '+84' + value[1:]
    check(bool(re.fullmatch(r'\+[1-9][0-9]{8,14}', value)), 'INVALID_PHONE', 'Số điện thoại không hợp lệ')
    return value

def email(value):
    value = text(value, 254, 3).casefold()
    check(bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value)), 'INVALID_EMAIL', 'Email không hợp lệ')
    return value

async def password_hash(value):
    check(isinstance(value,str) and 10<=len(value)<=128 and not value.isspace(),
          'INVALID_PASSWORD','Mật khẩu cần 10 đến 128 ký tự')
    return await asyncio.to_thread(hasher.hash, value)

def csrf(raw):
    return secret_hmac('csrf:' + raw).hex()

def profile(user):
    return {k: user[k] for k in ('id', 'phone_e164', 'email_normalized', 'display_name',
                               'role', 'status', 'group_id', 'default_address_id', 'version')}

async def rate(key, limit, seconds):
    """Independent transaction: failed attempts cannot roll back their own limit."""
    key = hashlib.sha256(key.encode()).hexdigest()
    t = T['rate_limit_buckets']
    async with Session.begin() as s:
        await s.execute(insert(t).values(bucket_key=key, window_started_at=now(),
                                         expires_at=now()+timedelta(seconds=seconds), count=0)
                        .on_duplicate_key_update(bucket_key=key))
        bucket = (await s.execute(select(t).where(t.c.bucket_key == key).with_for_update())).mappings().one()
        count = 0 if bucket['expires_at'] <= now() else bucket['count']
        check(count < limit, 'RATE_LIMITED', 'Thao tác quá nhanh, hãy thử lại sau', 429)
        values = {'count': count + 1}
        if bucket['expires_at'] <= now():
            values.update(window_started_at=now(), expires_at=now()+timedelta(seconds=seconds))
        await s.execute(update(t).where(t.c.bucket_key == key).values(**values))

async def authenticate(s, raw, activity=False):
    check(bool(raw), 'AUTH_REQUIRED', 'Vui lòng đăng nhập', 401)
    t, u = T['sessions'], T['users']
    row = (await s.execute(select(u, t.c.id.label('_session_id'), t.c.revoked_at.label('_revoked_at'),
                           t.c.security_version.label('_session_security'),
                           t.c.absolute_expires_at.label('_absolute_expires_at'), t.c.last_activity_at.label('_last_activity_at'))
                           .select_from(t).join(u, t.c.user_id == u.c.id).where(t.c.token_hash == hashed(raw)))).mappings().first()
    valid = row and not row['_revoked_at'] and row['status'] == 'ACTIVE' and \
        row['_session_security'] == row['security_version'] and row['_absolute_expires_at'] > now() and \
        row['_last_activity_at'] + timedelta(seconds=settings.idle_seconds) > now()
    check(valid, 'SESSION_EXPIRED', 'Phiên đã hết hạn hoặc bị thu hồi. Vui lòng đăng nhập lại.', 401)
    s.info['authenticated_session_id']=row['_session_id']
    if activity:
        await change(s, 'sessions', row['_session_id'], last_activity_at=now())
    return {column.name: row[column.name] for column in u.c}

def require_admin(user):
    check(user['role'] == 'ADMIN', 'FORBIDDEN', 'Thao tác dành cho quản trị viên', 403)

async def send_code(subject, code, purpose):
    """Called only after challenge commit. OTP is never logged or persisted in plain text."""
    if purpose == 'VERIFY_EMAIL':
        if settings.email_provider == 'demo':
            check(settings.demo_mode, 'EMAIL_NOT_CONFIGURED', 'Chưa cấu hình email', 503)
            return
        def send_mail():
            msg = EmailMessage()
            msg['Subject'], msg['From'], msg['To'] = 'Mã xác minh RealtimeOrders', settings.smtp_from, subject
            msg.set_content(f'Mã xác minh của bạn: {code}. Hiệu lực 5 phút.')
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
        await asyncio.to_thread(send_mail)
    elif settings.sms_provider == 'twilio':
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f'https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json',
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                data={'To': subject, 'From': settings.twilio_from, 'Body': f'RealtimeOrders: {code}. Hieu luc 5 phut.'})
            check(response.is_success, 'SMS_UNAVAILABLE', 'Không gửi được SMS. Vui lòng thử lại.', 503)
    else:
        check(settings.demo_mode, 'SMS_NOT_CONFIGURED', 'Chưa cấu hình SMS', 503)

async def challenge(subject, purpose, ip, user=None):
    await rate(f'otp-ip:{ip}', 20, 3600)
    await rate(f'otp-hour:{purpose}:{subject}', 5, 3600)
    await rate(f'otp-minute:{purpose}:{subject}', 1, 60)
    code = f'{secrets.randbelow(1000000):06d}'
    id = uid()
    async with Session.begin() as s:
        await add(s, 'auth_challenges', id=id, user_id=user['id'] if user else None,
                  purpose=purpose, subject=subject, secret_hmac=secret_hmac(id+':'+code),
                  attempts=0, state='CREATED', expires_at=now()+timedelta(minutes=5), created_at=now())
    try:
        await send_code(subject, code, purpose)
    except Exception:
        async with Session.begin() as s: await change(s, 'auth_challenges', id, state='FAILED')
        raise Fault('DELIVERY_FAILED', 'Không gửi được mã xác minh; vui lòng thử lại.', 503)
    async with Session.begin() as s: await change(s, 'auth_challenges', id, state='SENT')
    result = {'challengeId': id, 'expiresIn': 300, 'demo': settings.demo_mode}
    if settings.demo_mode: result['demoCode'] = code
    return result

async def verify_challenge(id, code, purpose):
    error = None
    ticket = secrets.token_urlsafe(32)
    async with Session.begin() as s:
        c = await one(s, 'auth_challenges', T['auth_challenges'].c.id == id, lock=True)
        check(c['purpose'] == purpose, 'INVALID_CHALLENGE', 'Mã xác minh không đúng mục đích')
        check(c['state'] == 'SENT' and c['expires_at'] > now() and c['attempts'] < 5,
              'OTP_EXPIRED', 'Mã đã hết hạn, đã sử dụng hoặc bị khóa')
        valid = isinstance(code, str) and hmac.compare_digest(c['secret_hmac'], secret_hmac(id+':'+code))
        if not valid:
            await change(s, 'auth_challenges', id, attempts=c['attempts']+1,
                         state='FAILED' if c['attempts']+1 >= 5 else 'SENT')
            error = Fault('OTP_INVALID', 'Mã xác minh không đúng')
        else:
            await change(s, 'auth_challenges', id, state='VERIFIED', verified_at=now(),
                         completion_ticket_hash=hashed(ticket))
    if error: raise error
    return {'ticket': ticket}

async def consume(s, ticket, purpose):
    c = await one(s, 'auth_challenges', T['auth_challenges'].c.completion_ticket_hash == hashed(text(ticket, 200, 20)), lock=True)
    check(c['state'] == 'VERIFIED' and c['purpose'] == purpose and c['expires_at'] > now(),
          'INVALID_TICKET', 'Xác minh đã hết hạn hoặc đã sử dụng')
    await change(s, 'auth_challenges', c['id'], state='CONSUMED', consumed_at=now())
    return c

async def login(s, identifier, password):
    ident = email(identifier) if '@' in str(identifier) else phone(identifier)
    col = T['users'].c.email_normalized if '@' in ident else T['users'].c.phone_e164
    user = await one(s, 'users', col == ident, required=False)
    try:
        valid = await asyncio.to_thread(hasher.verify, user['password_hash'] if user else DUMMY_HASH, str(password))
    except (VerifyMismatchError, InvalidHashError): valid = False
    check(user and valid and user['status'] == 'ACTIVE', 'LOGIN_FAILED', 'Thông tin đăng nhập không đúng hoặc tài khoản bị khóa', 401)
    raw = secrets.token_urlsafe(48)
    await add(s, 'sessions', id=uid(), user_id=user['id'], token_hash=hashed(raw),
              security_version=user['security_version'], created_at=now(), last_activity_at=now(),
              absolute_expires_at=now()+timedelta(seconds=settings.session_seconds))
    return user, raw
