"""Comments on visible daily sale posts."""
from alembic import op

revision = '0023'
down_revision = '0022'


def upgrade():
    op.execute('''CREATE TABLE post_comments (
        id CHAR(36) PRIMARY KEY,
        menu_id CHAR(36) NOT NULL,
        user_id CHAR(36) NOT NULL,
        body VARCHAR(1000) NOT NULL,
        created_at DATETIME(6) NOT NULL,
        CONSTRAINT fk_post_comment_menu FOREIGN KEY (menu_id) REFERENCES daily_menus(id),
        CONSTRAINT fk_post_comment_user FOREIGN KEY (user_id) REFERENCES users(id),
        KEY ix_post_comment_menu (menu_id, created_at, id),
        KEY ix_post_comment_user (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database.')
