import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from .config import settings

engine = create_async_engine(settings.database_url, pool_size=20, max_overflow=20, hide_parameters=True,
                             pool_pre_ping=True, isolation_level='READ COMMITTED')
Session = async_sessionmaker(engine, expire_on_commit=False)
metadata = MetaData()
T = {}

async def reflect():
    async with engine.connect() as conn:
        await conn.run_sync(metadata.reflect)
    T.update(metadata.tables)

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def uid():
    return str(uuid4())

def serialize(value):
    if isinstance(value, Decimal): return format(value, 'f')
    if isinstance(value, datetime): return value.isoformat() + 'Z'
    if hasattr(value, 'isoformat'): return value.isoformat()
    if isinstance(value, bytes): return value.hex()
    raise TypeError(type(value).__name__)

def public(value):
    result = json.loads(json.dumps(value, default=serialize, ensure_ascii=False))
    def versions(node):
        if isinstance(node, list): return [versions(v) for v in node]
        if isinstance(node, dict):
            return {k: str(v) if v is not None and (k in ('version','seq','last_seq') or k.endswith('_version'))
                    else versions(v) for k,v in node.items()}
        return node
    return versions(result)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=serialize,
                                     ensure_ascii=False, separators=(',', ':')).encode()).digest()

class Fault(Exception):
    def __init__(self, code, message, status=400, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details

def check(ok, code, message, status=400, details=None):
    if not ok: raise Fault(code, message, status, details)

def uuid(value):
    try: return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError): raise Fault('INVALID_ID', 'Mã yêu cầu không hợp lệ')

def text(value, maximum=1000, minimum=0):
    check(isinstance(value, str), 'INVALID_TEXT', 'Nội dung phải là chuỗi')
    value = value.strip()
    check(minimum <= len(value) <= maximum, 'INVALID_TEXT', f'Nội dung cần từ {minimum} đến {maximum} ký tự')
    return value

def number(value, places=3, minimum=Decimal('0'), maximum=Decimal('999999999')):
    try:
        d = Decimal(str(value))
        check(d.is_finite() and minimum <= d <= maximum and d == d.quantize(Decimal(10) ** -places),
              'INVALID_NUMBER', 'Số lượng hoặc giá không hợp lệ')
        return d
    except (InvalidOperation, ValueError): raise Fault('INVALID_NUMBER', 'Số không hợp lệ')

async def one(s, table, *conditions, lock=False, required=True):
    q = select(T[table]).where(*conditions)
    if lock: q = q.with_for_update()
    row = (await s.execute(q)).mappings().first()
    if required: check(row is not None, 'NOT_FOUND', 'Không tìm thấy dữ liệu', 404)
    return dict(row) if row else None

async def rows(s, table, *conditions, limit=100, order=None):
    q = select(T[table]).where(*conditions).limit(limit)
    if order is not None: q = q.order_by(*(order if isinstance(order, list) else [order]))
    return [dict(r) for r in (await s.execute(q)).mappings()]

async def add(s, table, **values):
    await s.execute(T[table].insert().values(**values))
    return values

async def change(s, table, id, **values):
    await s.execute(T[table].update().where(T[table].c.id == id).values(**values))
