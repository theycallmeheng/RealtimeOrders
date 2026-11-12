"""Threaded replies to comments on sale posts."""
from alembic import op

revision = '0025'
down_revision = '0024'


def upgrade():
    op.execute('''ALTER TABLE post_comments
        ADD COLUMN parent_id CHAR(36) NULL,
        ADD CONSTRAINT fk_post_comment_parent FOREIGN KEY (parent_id) REFERENCES post_comments(id),
        ADD KEY ix_post_comment_parent (parent_id, created_at)''')


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database.')
