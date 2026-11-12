"""Consolidate operations and start the warehouse with physical inventory counts."""
from alembic import op

revision = '0019'
down_revision = '0018'

STORE = '00000000-0000-4000-8000-000000000001'


def upgrade():
    op.execute("ALTER TABLE orders ADD legacy_store_order BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE orders ALTER COLUMN legacy_store_order SET DEFAULT FALSE")
    op.execute("ALTER TABLE daily_menus ADD legacy_store_menu BOOLEAN NOT NULL DEFAULT TRUE, ADD pickup_slot_ids JSON NULL")
    op.execute("ALTER TABLE daily_menus ALTER COLUMN legacy_store_menu SET DEFAULT FALSE")
    op.execute("UPDATE daily_menus SET status='CLOSED'")
    op.execute("UPDATE offers SET status='CLOSED' WHERE menu_id IS NULL")
    op.execute("ALTER TABLE offers ADD list_price DECIMAL(18,0) NULL, DROP FOREIGN KEY fk_offer_product_shop, DROP FOREIGN KEY fk_offer_menu_shop")
    op.execute("ALTER TABLE products ADD list_price DECIMAL(18,0) NULL, ADD vat_rate DECIMAL(5,2) NULL")
    op.execute("ALTER TABLE categories ADD vat_rate DECIMAL(5,2) NULL")
    op.execute("ALTER TABLE pickup_slots ADD allowed_group_ids JSON NULL")
    op.execute("ALTER TABLE order_items ADD vat_rate_snapshot DECIMAL(5,2) NULL, ADD vat_amount_snapshot DECIMAL(18,0) NULL, ADD list_price_snapshot DECIMAL(18,0) NULL")
    op.execute("ALTER TABLE orders MODIFY vat_rate DECIMAL(5,2) NULL")
    # MySQL gives the unnamed composite foreign key its own generated name.
    from sqlalchemy import inspect
    keys = inspect(op.get_bind()).get_foreign_keys('product_requests')
    product_key = next(key['name'] for key in keys if key['referred_table'] == 'products')
    op.drop_constraint(product_key, 'product_requests', type_='foreignkey')
    for table in ('products', 'daily_menus', 'offers', 'product_requests'):
        op.execute(f"UPDATE {table} SET shop_id='{STORE}' WHERE shop_id<>'{STORE}'")
    op.create_foreign_key('fk_request_product_store', 'product_requests', 'products', ['product_id','shop_id'], ['id','shop_id'])
    op.create_foreign_key('fk_offer_product_shop', 'offers', 'products', ['product_id','shop_id'], ['id','shop_id'])
    op.create_foreign_key('fk_offer_menu_shop', 'offers', 'daily_menus', ['menu_id','shop_id'], ['id','shop_id'])
    op.execute(f"UPDATE users SET shop_id='{STORE}' WHERE role='SELLER'")
    op.execute(f"UPDATE shops SET active=(id='{STORE}')")
    op.execute(f"UPDATE shops SET name='Food Mart', profile_json=JSON_SET(profile_json,'$.name','Food Mart') WHERE id='{STORE}'")
    op.execute("""INSERT INTO categories (id,name) SELECT UUID(), names.name FROM (
      SELECT 'Bánh kẹo & đồ ăn vặt' name UNION ALL SELECT 'Hóa phẩm & vệ sinh'
      UNION ALL SELECT 'Đồ gia dụng & tiện ích' UNION ALL SELECT 'Văn phòng phẩm'
      UNION ALL SELECT 'Chăm sóc cá nhân') names
      WHERE NOT EXISTS (SELECT 1 FROM categories c WHERE c.name=names.name)""")
    op.execute("""UPDATE products p JOIN categories old ON old.id=p.category_id
      JOIN categories target ON target.name=CASE
        WHEN old.name IN ('Đồ ăn vặt','Bánh kẹo','Bánh kẹo & snack') THEN 'Bánh kẹo & đồ ăn vặt'
        WHEN old.name IN ('Vệ sinh nhà cửa','Hóa phẩm','Vệ sinh gia dụng') THEN 'Hóa phẩm & vệ sinh'
        WHEN old.name IN ('Đồ gia dụng','Tiện ích','Đồ dùng gia đình') THEN 'Đồ gia dụng & tiện ích'
        ELSE NULL END SET p.category_id=target.id""")
    op.execute("""UPDATE categories c SET active=FALSE,version=version+1
      WHERE name IN ('Đồ ăn vặt','Bánh kẹo','Bánh kẹo & snack','Vệ sinh nhà cửa','Hóa phẩm',
                     'Vệ sinh gia dụng','Đồ gia dụng','Tiện ích','Đồ dùng gia đình')
        AND active=TRUE AND NOT EXISTS (SELECT 1 FROM products p WHERE p.category_id=c.id)""")
    op.execute("""CREATE TABLE product_stock (
      product_id CHAR(36) PRIMARY KEY, quantity DECIMAL(12,3) NOT NULL DEFAULT 0,
      average_cost DECIMAL(24,6) NULL, opened BOOLEAN NOT NULL DEFAULT FALSE,
      FOREIGN KEY(product_id) REFERENCES products(id), CHECK(quantity>=0), CHECK(average_cost>=0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("INSERT INTO product_stock(product_id) SELECT id FROM products")
    op.execute("""CREATE TABLE suppliers (
      id CHAR(36) PRIMARY KEY, name VARCHAR(150) NOT NULL, contact VARCHAR(200) NOT NULL,
      active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
      created_at DATETIME(6) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""CREATE TABLE stock_receipts (
      id CHAR(36) PRIMARY KEY, supplier_id CHAR(36) NULL, actor_id CHAR(36) NOT NULL,
      kind ENUM('OPENING','PURCHASE') NOT NULL, invoice_number VARCHAR(100) NOT NULL,
      due_date DATE NULL, note VARCHAR(500) NOT NULL, total DECIMAL(18,0) NOT NULL,
      confirmed_at DATETIME(6) NOT NULL,
      FOREIGN KEY(supplier_id) REFERENCES suppliers(id), FOREIGN KEY(actor_id) REFERENCES users(id),
      KEY ix_receipt_supplier(supplier_id,confirmed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""CREATE TABLE stock_receipt_items (
      receipt_id CHAR(36) NOT NULL, product_id CHAR(36) NOT NULL, quantity DECIMAL(12,3) NOT NULL,
      unit_cost DECIMAL(18,0) NOT NULL, line_total DECIMAL(18,0) NOT NULL,
      PRIMARY KEY(receipt_id,product_id), FOREIGN KEY(receipt_id) REFERENCES stock_receipts(id),
      FOREIGN KEY(product_id) REFERENCES products(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""CREATE TABLE supplier_payments (
      id CHAR(36) PRIMARY KEY, receipt_id CHAR(36) NOT NULL, actor_id CHAR(36) NOT NULL,
      amount DECIMAL(18,0) NOT NULL, reference VARCHAR(150) NOT NULL, paid_at DATETIME(6) NOT NULL,
      FOREIGN KEY(receipt_id) REFERENCES stock_receipts(id), FOREIGN KEY(actor_id) REFERENCES users(id),
      UNIQUE KEY uq_supplier_payment_ref(receipt_id,reference), CHECK(amount>0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""CREATE TABLE stock_ledger (
      id CHAR(36) PRIMARY KEY, product_id CHAR(36) NOT NULL, actor_id CHAR(36) NOT NULL,
      kind VARCHAR(32) NOT NULL, reference_id CHAR(36) NOT NULL,
      delta DECIMAL(12,3) NOT NULL, balance_after DECIMAL(12,3) NOT NULL,
      unit_cost DECIMAL(24,6) NULL, reason VARCHAR(500) NOT NULL, created_at DATETIME(6) NOT NULL,
      FOREIGN KEY(product_id) REFERENCES products(id), FOREIGN KEY(actor_id) REFERENCES users(id),
      KEY ix_stock_ledger_product(product_id,created_at), CHECK(balance_after>=0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("ALTER TABLE order_items MODIFY cost_price_snapshot DECIMAL(24,6) NULL")
    # Force snapshot sync so old catalog events cannot resurrect old shop data.
    op.execute("UPDATE system_settings SET value_json=JSON_OBJECT('value',UUID()),version=version+1 WHERE setting_key='dataset_epoch'")


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database.')
