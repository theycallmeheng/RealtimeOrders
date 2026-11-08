"""Identify stock restored after payment expiry or returned delivery."""
from alembic import op

revision='0015'
down_revision='0014'


def upgrade():
    op.execute("ALTER TABLE inventory_movements MODIFY kind ENUM('OPENING','APPROVE','CANCEL_RESTORE','MANUAL_ADJUST','PAYMENT_EXPIRED','DELIVERY_RETURN') NOT NULL")


def downgrade():
    raise RuntimeError('Preserve inventory audit history; restore a verified backup instead.')
