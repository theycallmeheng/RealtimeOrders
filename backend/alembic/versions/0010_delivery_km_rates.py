"""Support per-kilometer tiers without changing existing fee policies."""
from alembic import op
revision = '0010'
down_revision = '0009'

def upgrade():
    op.execute("ALTER TABLE delivery_policies ADD pricing_mode ENUM('BASE_PLUS_EXTRA','TIERED_KM') NOT NULL DEFAULT 'BASE_PLUS_EXTRA', ADD per_km_fee DECIMAL(18,0) NOT NULL DEFAULT 0, ADD distance_rounding ENUM('EXACT','CEIL_KM') NOT NULL DEFAULT 'EXACT'")

def downgrade():
    raise RuntimeError('Restore a backup into a separate database to preserve fee policy history.')
