"""Reactions on visible daily sale posts."""
from alembic import op

revision = '0024'
down_revision = '0023'


def upgrade():
    op.execute('''CREATE TABLE post_reactions (
        id CHAR(36) PRIMARY KEY,
        menu_id CHAR(36) NOT NULL,
        user_id CHAR(36) NOT NULL,
        reaction VARCHAR(10) NOT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        CONSTRAINT fk_post_reaction_menu FOREIGN KEY (menu_id) REFERENCES daily_menus(id),
        CONSTRAINT fk_post_reaction_user FOREIGN KEY (user_id) REFERENCES users(id),
        CONSTRAINT uq_post_reaction_user_menu UNIQUE (menu_id, user_id),
        KEY ix_post_reaction_menu (menu_id, reaction)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database.')
