"""Store an ordered gallery for each daily menu post."""
from alembic import op

revision = '0022'
down_revision = '0021'


def upgrade():
    op.execute('ALTER TABLE daily_menus ADD post_images JSON NULL')


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database.')
