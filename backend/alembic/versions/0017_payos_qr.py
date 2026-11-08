"""Keep signed payOS receiver details for repeatable in-app QR checkout."""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'


def upgrade():
    op.add_column('payment_requests', sa.Column('qr_code', sa.Text(), nullable=True))
    op.add_column('payment_requests', sa.Column('account_name', sa.String(255), nullable=True))
    op.add_column('payment_requests', sa.Column('account_number', sa.String(64), nullable=True))
    op.add_column('payment_requests', sa.Column('bank_bin', sa.String(32), nullable=True))


def downgrade():
    for column in ('qr_code', 'account_name', 'account_number', 'bank_bin'):
        op.drop_column('payment_requests', column)
