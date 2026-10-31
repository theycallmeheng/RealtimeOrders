"""Explicit menu-wide versus per-product audience selection."""
from alembic import op

revision = '0009'
down_revision = '0008'


def upgrade():
    op.execute("ALTER TABLE daily_menus ADD audience_mode ENUM('MENU','PRODUCT') NOT NULL DEFAULT 'MENU'")
    # Preserve existing individual overrides where no global audience was set.
    op.execute("""UPDATE daily_menus m SET audience_mode='PRODUCT'
        WHERE (m.allowed_group_ids IS NULL OR JSON_TYPE(m.allowed_group_ids)='NULL')
        AND EXISTS (SELECT 1 FROM offers o WHERE o.menu_id=m.id
            AND o.allowed_group_ids IS NOT NULL AND JSON_TYPE(o.allowed_group_ids)<>'NULL')""")


def downgrade():
    raise RuntimeError('Preserve audience policy history; restore a backup into a separate database.')
