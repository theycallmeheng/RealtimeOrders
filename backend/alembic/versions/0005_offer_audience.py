"""Add per-menu-item audience overrides."""
from alembic import op

revision = '0005'
down_revision = '0004'


def upgrade():
    op.execute('ALTER TABLE offers ADD allowed_group_ids JSON NULL')


def downgrade():
    raise RuntimeError('Preserve menu audience history; restore a backup into a new database instead.')
