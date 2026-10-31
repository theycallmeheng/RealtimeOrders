"""Public, administrator-confirmed address points; never harvested from customers."""
from alembic import op
revision='0012'
down_revision='0011'

def upgrade():
    op.execute("""CREATE TABLE verified_locations (
      id CHAR(36) PRIMARY KEY, label VARCHAR(500) NOT NULL,
      house_number VARCHAR(40) NOT NULL DEFAULT '', street VARCHAR(200) NOT NULL DEFAULT '',
      aliases JSON NOT NULL, latitude DECIMAL(10,7) NOT NULL, longitude DECIMAL(10,7) NOT NULL,
      active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
      updated_by CHAR(36) NOT NULL, created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
      FOREIGN KEY(updated_by) REFERENCES users(id),
      CHECK(latitude BETWEEN -90 AND 90), CHECK(longitude BETWEEN -180 AND 180)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

def downgrade():
    raise RuntimeError('Preserve confirmed locations; restore a backup into a separate database.')
