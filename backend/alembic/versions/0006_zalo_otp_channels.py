"""Track OTP delivery channels and one manual SMS fallback for registration."""
from alembic import op
from sqlalchemy import inspect

revision = '0006'
down_revision = '0005'


def upgrade():
    # The checked-in base schema already contains these fields. Older installed
    # databases do not, so add only missing columns and keep both paths valid.
    bind = op.get_bind()
    columns = {column['name'] for column in inspect(bind).get_columns('auth_challenges')}
    if 'delivery_channel' not in columns:
        op.execute("ALTER TABLE auth_challenges ADD delivery_channel ENUM('SMS','ZALO','DEMO','EMAIL') NOT NULL DEFAULT 'SMS'")
    if 'delivery_accepted_at' not in columns:
        op.execute('ALTER TABLE auth_challenges ADD delivery_accepted_at DATETIME(6) NULL')
    if 'sms_fallback_used_at' not in columns:
        op.execute('ALTER TABLE auth_challenges ADD sms_fallback_used_at DATETIME(6) NULL')
    op.execute("UPDATE auth_challenges SET delivery_channel='EMAIL' WHERE purpose='VERIFY_EMAIL'")


def downgrade():
    raise RuntimeError('Giữ lịch sử OTP; phục hồi backup vào database mới thay vì xóa cột.')
