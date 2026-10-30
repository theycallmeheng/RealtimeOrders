"""Generate product SKUs in a serialized, database-backed sequence."""
from alembic import op

revision = '0004'
down_revision = '0003'


def upgrade():
    op.execute("""CREATE TABLE sku_sequences (
      sequence_key VARCHAR(64) NOT NULL PRIMARY KEY,
      next_value BIGINT UNSIGNED NOT NULL,
      CHECK (next_value > 0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""INSERT INTO sku_sequences(sequence_key,next_value)
      SELECT 'product',COALESCE(MAX(CAST(SUBSTRING(sku,5) AS UNSIGNED)),0)+1
      FROM products WHERE sku REGEXP '^SKU-[0-9]+$'""")


def downgrade():
    raise RuntimeError('Preserve assigned product SKUs; restore a backup into a new database instead.')
