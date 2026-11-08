"""Give shop-owned records explicit ownership and preserve the original shop."""
from alembic import op
from sqlalchemy import inspect

revision = '0016'
down_revision = '0015'

DEFAULT_SHOP = '00000000-0000-4000-8000-000000000001'


def upgrade():
    op.execute("""CREATE TABLE shops (
      id CHAR(36) PRIMARY KEY, name VARCHAR(200) NOT NULL,
      profile_json JSON NOT NULL, warehouse_json JSON NULL, payout_json JSON NULL,
      active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
      warehouse_version BIGINT UNSIGNED NOT NULL DEFAULT 0,
      created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute(f"""INSERT INTO shops(id,name,profile_json,created_at,updated_at)
      VALUES ('{DEFAULT_SHOP}',
        COALESCE((SELECT JSON_UNQUOTE(JSON_EXTRACT(value_json,'$.name')) FROM system_settings WHERE setting_key='shop_profile'),'RealtimeOrders'),
        COALESCE((SELECT value_json FROM system_settings WHERE setting_key='shop_profile'),JSON_OBJECT()),
        UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""")
    op.execute("ALTER TABLE users ADD shop_id CHAR(36) NULL, ADD CONSTRAINT fk_user_shop FOREIGN KEY(shop_id) REFERENCES shops(id)")
    op.execute(f"UPDATE users SET shop_id='{DEFAULT_SHOP}' WHERE role='SELLER'")
    for table in ('products', 'daily_menus', 'offers', 'orders', 'conversations', 'delivery_quotes'):
        op.execute(f"ALTER TABLE {table} ADD shop_id CHAR(36) NOT NULL DEFAULT '{DEFAULT_SHOP}', "
                   f"ADD CONSTRAINT fk_{table}_shop FOREIGN KEY(shop_id) REFERENCES shops(id)")
    op.execute("ALTER TABLE offers ADD sale_price_override DECIMAL(18,0) NULL")
    op.execute("ALTER TABLE products ADD UNIQUE KEY uq_product_shop(id,shop_id)")
    op.execute("ALTER TABLE daily_menus ADD UNIQUE KEY uq_menu_shop(id,shop_id)")
    op.execute("""ALTER TABLE offers ADD CONSTRAINT fk_offer_product_shop FOREIGN KEY(product_id,shop_id) REFERENCES products(id,shop_id),
        ADD CONSTRAINT fk_offer_menu_shop FOREIGN KEY(menu_id,shop_id) REFERENCES daily_menus(id,shop_id)""")
    op.execute("""ALTER TABLE orders ADD shop_name_snapshot VARCHAR(200) NOT NULL DEFAULT 'RealtimeOrders',
        ADD platform_fee_rate DECIMAL(5,2) NULL DEFAULT NULL,
        ADD platform_fee DECIMAL(18,0) NOT NULL DEFAULT 0,
        ADD KEY ix_orders_shop_created(shop_id,created_at,id),
        ADD KEY ix_orders_shop_delivered(shop_id,delivered_at,id),
        ADD CHECK(platform_fee_rate BETWEEN 0 AND 100), ADD CHECK(platform_fee BETWEEN 0 AND merchandise_total)""")
    op.execute("UPDATE orders o JOIN shops s ON s.id=o.shop_id SET o.shop_name_snapshot=s.name")
    op.execute("ALTER TABLE conversations ADD UNIQUE KEY uq_conversation_customer_shop(customer_id,shop_id)")
    for index in inspect(op.get_bind()).get_indexes('conversations'):
        if index['unique'] and index['column_names'] == ['customer_id']:
            op.drop_index(index['name'], table_name='conversations')
    op.execute("""CREATE TABLE shop_applications (
      id CHAR(36) PRIMARY KEY, applicant_id CHAR(36) NOT NULL UNIQUE,
      shop_id CHAR(36) NULL, profile_json JSON NOT NULL,
      status ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
      decision_note VARCHAR(500) NOT NULL DEFAULT '', reviewed_by CHAR(36) NULL,
      version BIGINT UNSIGNED NOT NULL DEFAULT 1,
      created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
      FOREIGN KEY(applicant_id) REFERENCES users(id), FOREIGN KEY(reviewed_by) REFERENCES users(id),
      FOREIGN KEY(shop_id) REFERENCES shops(id), KEY ix_shop_application_status(status,created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""CREATE TABLE shop_withdrawals (
      id CHAR(36) PRIMARY KEY, shop_id CHAR(36) NOT NULL, requested_by CHAR(36) NOT NULL,
      amount DECIMAL(18,0) NOT NULL, period_month DATE NOT NULL,
      bank_snapshot JSON NOT NULL, status ENUM('PENDING','PAID','REJECTED') NOT NULL DEFAULT 'PENDING',
      bank_reference VARCHAR(128) NULL UNIQUE, decision_note VARCHAR(500) NOT NULL DEFAULT '',
      decided_by CHAR(36) NULL, decided_at DATETIME(6) NULL, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
      created_at DATETIME(6) NOT NULL,
      FOREIGN KEY(shop_id) REFERENCES shops(id), FOREIGN KEY(requested_by) REFERENCES users(id),
      FOREIGN KEY(decided_by) REFERENCES users(id), KEY ix_withdrawal_shop_month(shop_id,period_month,status), CHECK(amount>0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # Version cached responses and replay after introducing shop ownership.
    op.execute("UPDATE stream_events SET payload=JSON_OBJECT('refresh',TRUE) WHERE topic LIKE 'catalog:%'")


def downgrade():
    raise RuntimeError('Restore a verified backup before removing shop ownership and withdrawal records.')
