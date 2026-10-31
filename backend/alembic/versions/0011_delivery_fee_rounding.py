"""Round the final delivery fee upward to a configured VND increment."""
from alembic import op
revision='0011'
down_revision='0010'

def upgrade():
    op.execute('ALTER TABLE delivery_policies ADD fee_rounding_step DECIMAL(18,0) NOT NULL DEFAULT 1')

def downgrade():
    raise RuntimeError('Preserve fee policy history; restore a backup into a separate database.')
