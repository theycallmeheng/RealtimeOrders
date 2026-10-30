"""Daily menus, explicit audiences, cost snapshots and route quotes."""
from alembic import op

revision = '0003'
down_revision = '0002'


def upgrade():
    op.execute("""CREATE TABLE daily_menus (
      id CHAR(36) PRIMARY KEY, sale_date DATE NOT NULL UNIQUE,
      status ENUM('DRAFT','OPEN','CLOSED') NOT NULL DEFAULT 'DRAFT',
      opens_at DATETIME(6) NOT NULL, closes_at DATETIME(6) NOT NULL,
      allowed_group_ids JSON NULL, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
      created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
      CHECK(closes_at>opens_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute('ALTER TABLE products ADD allowed_group_ids JSON NULL, ADD default_cost_price DECIMAL(18,0) NULL, ADD default_sale_price DECIMAL(18,0) NULL')
    op.execute('ALTER TABLE offers ADD menu_id CHAR(36) NULL, ADD cost_price DECIMAL(18,0) NULL, ADD archived_at DATETIME(6) NULL, ADD CONSTRAINT fk_offer_menu FOREIGN KEY(menu_id) REFERENCES daily_menus(id), ADD UNIQUE KEY uq_menu_product(menu_id,product_id)')
    op.execute('ALTER TABLE order_items ADD cost_price_snapshot DECIMAL(18,0) NULL')
    op.execute('ALTER TABLE addresses ADD latitude DECIMAL(10,7) NULL, ADD longitude DECIMAL(10,7) NULL, ADD place_id VARCHAR(512) NULL')
    op.execute('ALTER TABLE delivery_policies ADD distance_enabled BOOLEAN NOT NULL DEFAULT FALSE, ADD included_km DECIMAL(8,3) NULL, ADD extra_km_fee DECIMAL(18,0) NULL, ADD max_distance_km DECIMAL(8,3) NULL')
    op.execute("""CREATE TABLE delivery_quotes (
      id CHAR(36) PRIMARY KEY, user_id CHAR(36) NOT NULL, address_id CHAR(36) NOT NULL,
      address_version BIGINT UNSIGNED NOT NULL, group_id CHAR(36) NOT NULL,
      policy_id CHAR(36) NOT NULL, policy_version BIGINT UNSIGNED NOT NULL,
      warehouse_version BIGINT UNSIGNED NOT NULL, cart_hash BINARY(32) NOT NULL,
      distance_meters INT UNSIGNED NOT NULL, duration_seconds INT UNSIGNED NOT NULL,
      shipping_fee DECIMAL(18,0) NOT NULL, expires_at DATETIME(6) NOT NULL,
      created_at DATETIME(6) NOT NULL, route_json JSON NULL,
      KEY ix_quote_expiry(expires_at), FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(address_id) REFERENCES addresses(id), FOREIGN KEY(policy_id) REFERENCES delivery_policies(id),
      FOREIGN KEY(group_id) REFERENCES customer_groups(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # Legacy IDs and cost uncertainty are preserved. Daily semantics start with 28/10.
    op.execute("UPDATE offers SET archived_at=UTC_TIMESTAMP(6),status='CLOSED' WHERE sale_date<'2026-10-28'")
    op.execute("""INSERT INTO daily_menus(id,sale_date,status,opens_at,closes_at,created_at,updated_at)
      SELECT UUID(),sale_date,IF(sale_date<DATE(UTC_TIMESTAMP()+INTERVAL 7 HOUR),'CLOSED','DRAFT'),
      TIMESTAMP(sale_date)-INTERVAL 7 HOUR,TIMESTAMP(sale_date)+INTERVAL 17 HOUR,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)
      FROM offers WHERE archived_at IS NULL GROUP BY sale_date""")
    op.execute("""UPDATE offers o JOIN (SELECT sale_date,product_id,MIN(id) AS id FROM offers
      WHERE archived_at IS NULL GROUP BY sale_date,product_id) chosen ON chosen.id=o.id
      JOIN daily_menus m ON m.sale_date=o.sale_date
      SET o.menu_id=m.id,o.opens_at=m.opens_at,o.closes_at=m.closes_at""")
    op.execute("UPDATE offers SET archived_at=UTC_TIMESTAMP(6),status='CLOSED' WHERE menu_id IS NULL AND archived_at IS NULL")
    op.execute("""INSERT INTO system_settings(setting_key,value_json,version,updated_by,updated_at)
      SELECT 'dataset_epoch',JSON_OBJECT('value',UUID()),1,id,UTC_TIMESTAMP(6) FROM users WHERE role='ADMIN' LIMIT 1""")


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database to preserve history.')
