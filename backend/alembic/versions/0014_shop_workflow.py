"""Single-shop roles, tax snapshots, delivery, payments and reviews."""
from alembic import op
from sqlalchemy import text

revision = '0014'
down_revision = '0013'


def upgrade():
    op.execute("ALTER TABLE users MODIFY role ENUM('CUSTOMER','ADMIN','SELLER','SHIPPER') NOT NULL")
    op.execute("ALTER TABLE orders MODIFY status ENUM('PENDING','APPROVED','REJECTED','PREPARING','SHIPPING','DELIVERED','CANCELLED','READY_FOR_PICKUP','DELIVERY_FAILED') NOT NULL")
    bind = op.get_bind()
    for name, clause in bind.execute(text("SELECT tc.CONSTRAINT_NAME, cc.CHECK_CLAUSE FROM information_schema.TABLE_CONSTRAINTS tc JOIN information_schema.CHECK_CONSTRAINTS cc ON cc.CONSTRAINT_SCHEMA=tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME=tc.CONSTRAINT_NAME WHERE tc.TABLE_SCHEMA=DATABASE() AND tc.TABLE_NAME='orders' AND tc.CONSTRAINT_TYPE='CHECK'")):
        normalized = ''.join(clause.replace('`', '').split()).replace('(', '').replace(')', '')
        if normalized == 'total=merchandise_total+shipping_fee':
            bind.exec_driver_sql('ALTER TABLE orders DROP CHECK `' + name.replace('`', '``') + '`')
    op.execute("""ALTER TABLE orders
      ADD vat_rate DECIMAL(5,2) NOT NULL DEFAULT 0,
      ADD vat_amount DECIMAL(18,0) NOT NULL DEFAULT 0,
      ADD payment_method ENUM('LEGACY','COD','PAYOS') NOT NULL DEFAULT 'LEGACY',
      ADD payment_status ENUM('LEGACY','UNPAID','PAID','REFUND_PENDING','REFUNDED') NOT NULL DEFAULT 'LEGACY',
      ADD payment_deadline DATETIME(6) NULL,
      ADD courier_id CHAR(36) NULL,
      ADD CONSTRAINT fk_order_courier FOREIGN KEY(courier_id) REFERENCES users(id),
      ADD KEY ix_order_courier(courier_id,status),
      ADD CONSTRAINT ck_order_tax CHECK(vat_amount>=0 AND vat_rate BETWEEN 0 AND 100),
      ADD CONSTRAINT ck_order_total_tax CHECK(total=merchandise_total+vat_amount+shipping_fee)""")
    op.execute("""ALTER TABLE daily_menus ADD post_title VARCHAR(150) NOT NULL DEFAULT '',
      ADD post_body VARCHAR(2000) NOT NULL DEFAULT '', ADD post_image_url VARCHAR(2048) NULL,
      ADD receiving_note VARCHAR(500) NOT NULL DEFAULT '', ADD announced_at DATETIME(6) NULL""")
    op.execute("""CREATE TABLE payment_requests (
      id CHAR(36) PRIMARY KEY, order_id CHAR(36) NOT NULL UNIQUE,
      order_code BIGINT UNSIGNED NOT NULL AUTO_INCREMENT UNIQUE,
      provider_link_id VARCHAR(128) NULL UNIQUE, checkout_url VARCHAR(2048) NULL,
      state VARCHAR(24) NOT NULL DEFAULT 'CREATING', amount DECIMAL(18,0) NOT NULL,
      expires_at DATETIME(6) NOT NULL, created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
      FOREIGN KEY(order_id) REFERENCES orders(id), CHECK(amount>0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=100000""")
    op.execute("""CREATE TABLE money_entries (
      id CHAR(36) PRIMARY KEY, order_id CHAR(36) NOT NULL, kind ENUM('PAYMENT','REFUND') NOT NULL,
      method ENUM('PAYOS','COD','BANK_REFUND') NOT NULL, amount DECIMAL(18,0) NOT NULL,
      provider_ref VARCHAR(128) NULL UNIQUE, actor_id CHAR(36) NULL, collector_id CHAR(36) NULL,
      remitted_by CHAR(36) NULL, remitted_at DATETIME(6) NULL, note VARCHAR(500) NOT NULL DEFAULT '',
      created_at DATETIME(6) NOT NULL, FOREIGN KEY(order_id) REFERENCES orders(id),
      FOREIGN KEY(actor_id) REFERENCES users(id), FOREIGN KEY(collector_id) REFERENCES users(id),
      FOREIGN KEY(remitted_by) REFERENCES users(id), KEY ix_money_date(created_at), CHECK(amount>0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""CREATE TABLE refund_requests (
      id CHAR(36) PRIMARY KEY, order_id CHAR(36) NOT NULL UNIQUE, amount DECIMAL(18,0) NOT NULL,
      state ENUM('PENDING','COMPLETED') NOT NULL DEFAULT 'PENDING',
      completed_by CHAR(36) NULL, reference VARCHAR(128) NULL, note VARCHAR(500) NOT NULL DEFAULT '',
      created_at DATETIME(6) NOT NULL, completed_at DATETIME(6) NULL,
      FOREIGN KEY(order_id) REFERENCES orders(id), FOREIGN KEY(completed_by) REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""CREATE TABLE reviews (
      id CHAR(36) PRIMARY KEY, order_id CHAR(36) NOT NULL, customer_id CHAR(36) NOT NULL,
      target_key VARCHAR(80) NOT NULL, product_id CHAR(36) NULL, courier_id CHAR(36) NULL,
      rating TINYINT UNSIGNED NOT NULL, comment VARCHAR(1000) NOT NULL DEFAULT '',
      hidden BOOLEAN NOT NULL DEFAULT FALSE, hidden_reason VARCHAR(500) NULL,
      created_at DATETIME(6) NOT NULL, UNIQUE KEY uq_review(order_id,target_key),
      FOREIGN KEY(order_id) REFERENCES orders(id), FOREIGN KEY(customer_id) REFERENCES users(id),
      FOREIGN KEY(product_id) REFERENCES products(id), FOREIGN KEY(courier_id) REFERENCES users(id),
      CHECK(rating BETWEEN 1 AND 5)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    op.execute("""INSERT INTO system_settings(setting_key,value_json,version,updated_by,updated_at)
      SELECT 'shop_profile',JSON_OBJECT('name','RealtimeOrders','description','','address','96A Trần Phú, Hà Đông, Hà Nội','phone','','businessType','INDIVIDUAL','taxCode','','registrationNumber','','logoUrl','','coverUrl',''),1,id,UTC_TIMESTAMP(6) FROM users WHERE role='ADMIN' ORDER BY created_at LIMIT 1""")
    op.execute("""INSERT INTO system_settings(setting_key,value_json,version,updated_by,updated_at)
      SELECT 'vat_policy',JSON_OBJECT('rate',0),1,id,UTC_TIMESTAMP(6) FROM users WHERE role='ADMIN' ORDER BY created_at LIMIT 1""")


def downgrade():
    raise RuntimeError('Financial history must be preserved. Restore a verified backup into a separate database.')
