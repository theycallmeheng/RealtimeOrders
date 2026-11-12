"""Attach uploaded cover images to daily menu posts."""
from alembic import op

revision = '0021'
down_revision = '0020'


def upgrade():
    op.execute("ALTER TABLE media_assets MODIFY purpose ENUM('PRODUCT','CHAT','MENU_POST') NOT NULL")
    op.execute("""
        ALTER TABLE daily_menus ADD post_image_asset_id CHAR(36) NULL,
        ADD CONSTRAINT fk_daily_menu_post_image FOREIGN KEY (post_image_asset_id) REFERENCES media_assets(id),
        ADD CONSTRAINT ck_daily_menu_post_image_source CHECK (post_image_asset_id IS NULL OR post_image_url IS NULL)
    """)


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database.')
