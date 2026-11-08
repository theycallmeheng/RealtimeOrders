"""Private customer product requests, without quotes or order reservations."""
from alembic import op

revision = '0018'
down_revision = '0017'


def upgrade():
    op.execute("""CREATE TABLE product_requests (
      id CHAR(36) PRIMARY KEY, customer_id CHAR(36) NOT NULL, shop_id CHAR(36) NOT NULL,
      name VARCHAR(200) NOT NULL, name_key CHAR(64) NOT NULL, description TEXT NOT NULL,
      quantity DECIMAL(18,3) NOT NULL, unit_label VARCHAR(40) NOT NULL,
      image_url VARCHAR(2048) NOT NULL DEFAULT '', reference_url VARCHAR(2048) NOT NULL DEFAULT '',
      desired_price DECIMAL(18,0) NULL,
      status ENUM('PENDING','REVIEWING','WAITING','OPENED','REJECTED','CANCELLED') NOT NULL DEFAULT 'PENDING',
      product_id CHAR(36) NULL, offer_id CHAR(36) NULL, decision_note VARCHAR(1000) NOT NULL DEFAULT '',
      history JSON NOT NULL, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
      created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
      FOREIGN KEY(customer_id) REFERENCES users(id), FOREIGN KEY(shop_id) REFERENCES shops(id),
      FOREIGN KEY(product_id,shop_id) REFERENCES products(id,shop_id), FOREIGN KEY(offer_id) REFERENCES offers(id),
      KEY ix_request_customer_date(customer_id,created_at,id),
      KEY ix_request_shop_status(shop_id,status,created_at,id),
      KEY ix_request_duplicate(customer_id,shop_id,name_key,status),
      KEY ix_request_waiting(status,product_id), CHECK(quantity>0), CHECK(desired_price IS NULL OR desired_price>=0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


def downgrade():
    op.drop_table('product_requests')
