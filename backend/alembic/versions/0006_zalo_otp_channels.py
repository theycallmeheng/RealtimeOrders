"""Track OTP delivery channels and one manual SMS fallback for registration."""
from alembic import op

revision = '0006'
down_revision = '0005'


def upgrade():
    op.execute("ALTER TABLE auth_challenges ADD delivery_channel ENUM('SMS','ZALO','DEMO','EMAIL') NOT NULL DEFAULT 'SMS'")
    op.execute('ALTER TABLE auth_challenges ADD delivery_accepted_at DATETIME(6) NULL')
    op.execute('ALTER TABLE auth_challenges ADD sms_fallback_used_at DATETIME(6) NULL')
    op.execute("UPDATE auth_challenges SET delivery_channel='EMAIL' WHERE purpose='VERIFY_EMAIL'")


def downgrade():
    raise RuntimeError('Giữ lịch sử OTP; phục hồi backup vào database mới thay vì xóa cột.')
