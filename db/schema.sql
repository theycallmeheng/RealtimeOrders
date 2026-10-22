-- RealtimeOrders initial schema, consumed by Alembic revision 0001.
-- Executed and tested on MySQL 8.0.46 / InnoDB on 22 October 2026.
-- Run only in a newly created database chosen for this project; no DROP or USE.
-- All DATETIME(6) values are UTC; application controls timestamps and versions.
SET NAMES utf8mb4;

CREATE TABLE customer_groups (
  id CHAR(36) PRIMARY KEY, code VARCHAR(32) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE users (
  id CHAR(36) PRIMARY KEY,
  phone_e164 VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
  email_normalized VARCHAR(254) COLLATE utf8mb4_bin NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL, display_name VARCHAR(100) NOT NULL,
  role ENUM('CUSTOMER','ADMIN') NOT NULL,
  status ENUM('ACTIVE','LOCKED','DELETED') NOT NULL DEFAULT 'ACTIVE',
  group_id CHAR(36) NULL, default_address_id CHAR(36) NULL,
  phone_verified_at DATETIME(6) NOT NULL, email_verified_at DATETIME(6) NULL,
  security_version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  FOREIGN KEY (group_id) REFERENCES customer_groups(id),
  CHECK ((email_normalized IS NULL AND email_verified_at IS NULL)
      OR (email_normalized IS NOT NULL AND email_verified_at IS NOT NULL)),
  CHECK (role = 'ADMIN' OR group_id IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE delivery_zones (
  id CHAR(36) PRIMARY KEY, code VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(150) NOT NULL, description TEXT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE addresses (
  id CHAR(36) PRIMARY KEY, user_id CHAR(36) NOT NULL,
  zone_id CHAR(36) NOT NULL, recipient_name VARCHAR(100) NOT NULL,
  phone_e164 VARCHAR(16) NOT NULL, address_line VARCHAR(500) NOT NULL,
  note VARCHAR(500) NULL, deleted_at DATETIME(6) NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_address_owner (user_id,id),
  KEY ix_address_active (user_id,deleted_at),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (zone_id) REFERENCES delivery_zones(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE users ADD CONSTRAINT fk_user_default_address
  FOREIGN KEY (id,default_address_id) REFERENCES addresses(user_id,id);

CREATE TABLE auth_challenges (
  id CHAR(36) PRIMARY KEY, user_id CHAR(36) NULL,
  purpose ENUM('REGISTER_PHONE','RESET_PASSWORD','VERIFY_EMAIL') NOT NULL,
  subject VARCHAR(254) NOT NULL, secret_hmac BINARY(32) NOT NULL,
  completion_ticket_hash BINARY(32) NULL UNIQUE,
  attempts SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  state ENUM('CREATED','SENT','VERIFIED','CONSUMED','FAILED') NOT NULL,
  expires_at DATETIME(6) NOT NULL, verified_at DATETIME(6) NULL,
  consumed_at DATETIME(6) NULL, provider_reference VARCHAR(191) NULL,
  created_at DATETIME(6) NOT NULL,
  KEY ix_challenge_subject (subject,purpose,created_at),
  KEY ix_challenge_expiry (expires_at),
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sessions (
  id CHAR(36) PRIMARY KEY, user_id CHAR(36) NOT NULL,
  token_hash BINARY(32) NOT NULL UNIQUE,
  security_version BIGINT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL, last_activity_at DATETIME(6) NOT NULL,
  absolute_expires_at DATETIME(6) NOT NULL, revoked_at DATETIME(6) NULL,
  KEY ix_session_user (user_id,revoked_at),
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rate_limit_buckets (
  bucket_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  window_started_at DATETIME(6) NOT NULL, expires_at DATETIME(6) NOT NULL,
  count INT UNSIGNED NOT NULL DEFAULT 0,
  KEY ix_rate_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE categories (
  id CHAR(36) PRIMARY KEY, name VARCHAR(100) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE units (
  id CHAR(36) PRIMARY KEY, code VARCHAR(32) NOT NULL UNIQUE,
  label VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE media_assets (
  id CHAR(36) PRIMARY KEY, owner_id CHAR(36) NOT NULL,
  purpose ENUM('PRODUCT','CHAT') NOT NULL,
  state ENUM('UPLOADING','READY','REJECTED','DELETED') NOT NULL,
  storage_key VARCHAR(191) NOT NULL UNIQUE, mime_type VARCHAR(64) NOT NULL,
  size_bytes BIGINT UNSIGNED NOT NULL, width INT UNSIGNED NULL,
  height INT UNSIGNED NULL, content_sha256 BINARY(32) NULL,
  created_at DATETIME(6) NOT NULL, expires_at DATETIME(6) NULL,
  FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE products (
  id CHAR(36) PRIMARY KEY, category_id CHAR(36) NOT NULL, unit_id CHAR(36) NOT NULL,
  sku VARCHAR(64) NOT NULL UNIQUE, name VARCHAR(150) NOT NULL,
  description VARCHAR(2000) NULL, quantity_step DECIMAL(12,3) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE, deleted_at DATETIME(6) NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  FOREIGN KEY (category_id) REFERENCES categories(id),
  FOREIGN KEY (unit_id) REFERENCES units(id), CHECK (quantity_step > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE product_images (
  product_id CHAR(36) NOT NULL, asset_id CHAR(36) NOT NULL,
  position SMALLINT UNSIGNED NOT NULL,
  PRIMARY KEY (product_id,asset_id), UNIQUE KEY uq_product_image_position (product_id,position),
  FOREIGN KEY (product_id) REFERENCES products(id),
  FOREIGN KEY (asset_id) REFERENCES media_assets(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE offers (
  id CHAR(36) PRIMARY KEY, product_id CHAR(36) NOT NULL,
  sale_date DATE NOT NULL, batch_code VARCHAR(64) NOT NULL,
  status ENUM('DRAFT','OPEN','CLOSED') NOT NULL DEFAULT 'DRAFT',
  available_qty DECIMAL(12,3) NOT NULL,
  opens_at DATETIME(6) NOT NULL, closes_at DATETIME(6) NOT NULL,
  processing_locked_at DATETIME(6) NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_offer_batch (product_id,sale_date,batch_code),
  KEY ix_offer_catalog (status,sale_date,opens_at,closes_at),
  FOREIGN KEY (product_id) REFERENCES products(id),
  CHECK (available_qty >= 0), CHECK (closes_at > opens_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE offer_prices (
  offer_id CHAR(36) NOT NULL, group_id CHAR(36) NOT NULL,
  unit_price DECIMAL(18,0) NOT NULL, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  PRIMARY KEY (offer_id,group_id),
  FOREIGN KEY (offer_id) REFERENCES offers(id),
  FOREIGN KEY (group_id) REFERENCES customer_groups(id), CHECK (unit_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE delivery_policies (
  id CHAR(36) PRIMARY KEY, group_id CHAR(36) NOT NULL, zone_id CHAR(36) NOT NULL,
  method ENUM('COLLECTIVE','INDIVIDUAL') NOT NULL,
  minimum_subtotal DECIMAL(18,0) NOT NULL DEFAULT 0,
  shipping_fee DECIMAL(18,0) NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  UNIQUE KEY uq_delivery_policy (group_id,zone_id,method),
  FOREIGN KEY (group_id) REFERENCES customer_groups(id),
  FOREIGN KEY (zone_id) REFERENCES delivery_zones(id),
  CHECK (minimum_subtotal >= 0), CHECK (shipping_fee >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE pickup_slots (
  id CHAR(36) PRIMARY KEY, zone_id CHAR(36) NOT NULL,
  name VARCHAR(150) NOT NULL, address_line VARCHAR(500) NOT NULL,
  starts_at DATETIME(6) NOT NULL, ends_at DATETIME(6) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  FOREIGN KEY (zone_id) REFERENCES delivery_zones(id), CHECK (ends_at > starts_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE product_requests (
  id CHAR(36) PRIMARY KEY, customer_id CHAR(36) NOT NULL,
  item_name VARCHAR(150) NOT NULL, unit_label VARCHAR(40) NOT NULL,
  quantity DECIMAL(12,3) NOT NULL, needed_by DATETIME(6) NULL,
  note VARCHAR(2000) NULL,
  status ENUM('NEW','RECEIVED','QUOTED','ACCEPTED','CONVERTED','REJECTED','CANCELLED') NOT NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  KEY ix_request_customer (customer_id,created_at,id),
  FOREIGN KEY (customer_id) REFERENCES users(id), CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE request_quotes (
  id CHAR(36) PRIMARY KEY, request_id CHAR(36) NOT NULL,
  revision INT UNSIGNED NOT NULL, created_by CHAR(36) NOT NULL,
  offer_id CHAR(36) NOT NULL, quantity DECIMAL(12,3) NOT NULL,
  unit_price DECIMAL(18,0) NOT NULL, shipping_fee DECIMAL(18,0) NOT NULL,
  delivery_snapshot JSON NOT NULL,
  expires_at DATETIME(6) NOT NULL, accepted_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_request_quote_revision (request_id,revision),
  FOREIGN KEY (request_id) REFERENCES product_requests(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  FOREIGN KEY (offer_id) REFERENCES offers(id),
  CHECK (quantity > 0), CHECK (unit_price >= 0), CHECK (shipping_fee >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE orders (
  id CHAR(36) PRIMARY KEY, customer_id CHAR(36) NOT NULL,
  client_order_id CHAR(36) NOT NULL, request_hash BINARY(32) NOT NULL,
  source_request_id CHAR(36) NULL UNIQUE, source_quote_id CHAR(36) NULL UNIQUE,
  status ENUM('PENDING','APPROVED','REJECTED','PREPARING','SHIPPING','DELIVERED','CANCELLED') NOT NULL,
  group_snapshot JSON NOT NULL, address_snapshot JSON NOT NULL,
  delivery_snapshot JSON NOT NULL, note VARCHAR(1000) NULL,
  delivery_method ENUM('COLLECTIVE','INDIVIDUAL') NOT NULL,
  merchandise_total DECIMAL(18,0) NOT NULL, shipping_fee DECIMAL(18,0) NOT NULL,
  total DECIMAL(18,0) NOT NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  approved_at DATETIME(6) NULL, shipped_at DATETIME(6) NULL,
  delivered_at DATETIME(6) NULL, cancelled_at DATETIME(6) NULL,
  UNIQUE KEY uq_customer_order (customer_id,client_order_id),
  KEY ix_order_customer (customer_id,created_at,id),
  KEY ix_order_status (status,created_at,id), KEY ix_order_revenue (delivered_at),
  FOREIGN KEY (customer_id) REFERENCES users(id),
  FOREIGN KEY (source_request_id) REFERENCES product_requests(id),
  FOREIGN KEY (source_quote_id) REFERENCES request_quotes(id),
  CHECK (merchandise_total >= 0), CHECK (shipping_fee >= 0),
  CHECK (total = merchandise_total + shipping_fee)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE order_items (
  id CHAR(36) PRIMARY KEY, order_id CHAR(36) NOT NULL, offer_id CHAR(36) NOT NULL,
  product_name_snapshot VARCHAR(150) NOT NULL, unit_snapshot VARCHAR(40) NOT NULL,
  quantity DECIMAL(12,3) NOT NULL, unit_price DECIMAL(18,0) NOT NULL,
  price_version BIGINT UNSIGNED NOT NULL, line_total DECIMAL(18,0) NOT NULL,
  UNIQUE KEY uq_order_offer (order_id,offer_id), KEY ix_item_offer (offer_id,order_id),
  FOREIGN KEY (order_id) REFERENCES orders(id), FOREIGN KEY (offer_id) REFERENCES offers(id),
  CHECK (quantity > 0), CHECK (unit_price >= 0), CHECK (line_total >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE order_status_history (
  id CHAR(36) PRIMARY KEY, order_id CHAR(36) NOT NULL, actor_id CHAR(36) NOT NULL,
  from_status VARCHAR(32) NULL, to_status VARCHAR(32) NOT NULL,
  order_version BIGINT UNSIGNED NOT NULL, reason VARCHAR(1000) NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_order_history_version (order_id,order_version),
  FOREIGN KEY (order_id) REFERENCES orders(id), FOREIGN KEY (actor_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE cancellation_requests (
  id CHAR(36) PRIMARY KEY, order_id CHAR(36) NOT NULL, requested_by CHAR(36) NOT NULL,
  reason VARCHAR(1000) NOT NULL, state ENUM('OPEN','ACCEPTED','REJECTED') NOT NULL,
  open_order_id CHAR(36) GENERATED ALWAYS AS
    (CASE WHEN state = 'OPEN' THEN order_id ELSE NULL END) STORED,
  decision_by CHAR(36) NULL, decision_note VARCHAR(1000) NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, decided_at DATETIME(6) NULL,
  UNIQUE KEY uq_open_cancellation (open_order_id),
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (requested_by) REFERENCES users(id), FOREIGN KEY (decision_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE inventory_movements (
  id CHAR(36) PRIMARY KEY, offer_id CHAR(36) NOT NULL, actor_id CHAR(36) NOT NULL,
  kind ENUM('OPENING','APPROVE','CANCEL_RESTORE','MANUAL_ADJUST') NOT NULL,
  reference_id CHAR(36) NOT NULL, order_id CHAR(36) NULL,
  quantity_delta DECIMAL(12,3) NOT NULL, balance_after DECIMAL(12,3) NOT NULL,
  reason VARCHAR(1000) NULL, created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_movement_reference (kind,reference_id,offer_id),
  KEY ix_movement_offer (offer_id,created_at,id),
  FOREIGN KEY (offer_id) REFERENCES offers(id), FOREIGN KEY (actor_id) REFERENCES users(id),
  FOREIGN KEY (order_id) REFERENCES orders(id),
  CHECK (quantity_delta <> 0), CHECK (balance_after >= 0),
  CHECK (kind <> 'APPROVE' OR quantity_delta < 0),
  CHECK (kind <> 'CANCEL_RESTORE' OR quantity_delta > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE request_status_history (
  id CHAR(36) PRIMARY KEY, request_id CHAR(36) NOT NULL, actor_id CHAR(36) NOT NULL,
  from_status VARCHAR(32) NULL, to_status VARCHAR(32) NOT NULL,
  request_version BIGINT UNSIGNED NOT NULL, note VARCHAR(1000) NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_request_history_version (request_id,request_version),
  FOREIGN KEY (request_id) REFERENCES product_requests(id), FOREIGN KEY (actor_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE conversations (
  id CHAR(36) PRIMARY KEY, customer_id CHAR(36) NOT NULL UNIQUE,
  created_at DATETIME(6) NOT NULL,
  FOREIGN KEY (customer_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE messages (
  id CHAR(36) PRIMARY KEY, conversation_id CHAR(36) NOT NULL, sender_id CHAR(36) NOT NULL,
  client_message_id CHAR(36) NOT NULL, request_hash BINARY(32) NOT NULL,
  text_sanitized VARCHAR(4000) NULL, created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_sender_message (sender_id,client_message_id),
  KEY ix_message_history (conversation_id,created_at,id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(id), FOREIGN KEY (sender_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE message_attachments (
  message_id CHAR(36) NOT NULL, asset_id CHAR(36) NOT NULL,
  position SMALLINT UNSIGNED NOT NULL, PRIMARY KEY (message_id,asset_id),
  UNIQUE KEY uq_message_attachment_position (message_id,position),
  FOREIGN KEY (message_id) REFERENCES messages(id), FOREIGN KEY (asset_id) REFERENCES media_assets(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE notifications (
  id CHAR(36) PRIMARY KEY, user_id CHAR(36) NOT NULL, source_event_id CHAR(36) NOT NULL,
  kind VARCHAR(64) NOT NULL, payload JSON NOT NULL,
  created_at DATETIME(6) NOT NULL, read_at DATETIME(6) NULL,
  UNIQUE KEY uq_notification_source (user_id,source_event_id,kind),
  KEY ix_notification_feed (user_id,created_at,id),
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE product_subscriptions (
  user_id CHAR(36) NOT NULL, product_id CHAR(36) NOT NULL, created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (user_id,product_id),
  FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE notification_jobs (
  id CHAR(36) PRIMARY KEY, source_fact_id CHAR(36) NOT NULL,
  kind VARCHAR(64) NOT NULL, product_id CHAR(36) NOT NULL,
  payload JSON NOT NULL, after_user_id CHAR(36) NULL,
  state ENUM('PENDING','LEASED','COMPLETED') NOT NULL DEFAULT 'PENDING',
  lease_until DATETIME(6) NULL, attempts INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL, completed_at DATETIME(6) NULL,
  UNIQUE KEY uq_notification_job_fact (source_fact_id,kind),
  KEY ix_notification_job_state (state,lease_until),
  FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE moderation_rules (
  id CHAR(36) PRIMARY KEY, phrase_normalized VARCHAR(150) COLLATE utf8mb4_bin NOT NULL,
  match_mode ENUM('TOKEN','PHRASE') NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE, version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  UNIQUE KEY uq_moderation_phrase (phrase_normalized,match_mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE moderation_violations (
  id CHAR(36) PRIMARY KEY, user_id CHAR(36) NOT NULL, rule_id CHAR(36) NULL,
  field_name VARCHAR(64) NOT NULL, reference_id CHAR(36) NULL,
  original_restricted TEXT NOT NULL, sanitized TEXT NOT NULL,
  created_at DATETIME(6) NOT NULL,
  KEY ix_violation_user (user_id,created_at),
  FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (rule_id) REFERENCES moderation_rules(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE audit_logs (
  id CHAR(36) PRIMARY KEY, actor_id CHAR(36) NULL, action VARCHAR(100) NOT NULL,
  entity_type VARCHAR(64) NOT NULL, entity_id CHAR(36) NULL,
  before_data JSON NULL, after_data JSON NULL,
  request_id CHAR(36) NOT NULL, created_at DATETIME(6) NOT NULL,
  KEY ix_audit_entity (entity_type,entity_id,created_at),
  FOREIGN KEY (actor_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE system_settings (
  setting_key VARCHAR(100) PRIMARY KEY, value_json JSON NOT NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  updated_by CHAR(36) NOT NULL, updated_at DATETIME(6) NOT NULL,
  FOREIGN KEY (updated_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE idempotency_keys (
  actor_id CHAR(36) NOT NULL, scope VARCHAR(128) NOT NULL, key_uuid CHAR(36) NOT NULL,
  request_hash BINARY(32) NOT NULL,
  state ENUM('IN_PROGRESS','COMPLETED') NOT NULL,
  http_status SMALLINT UNSIGNED NULL, response_body JSON NULL,
  created_at DATETIME(6) NOT NULL, expires_at DATETIME(6) NOT NULL,
  PRIMARY KEY (actor_id,scope,key_uuid), KEY ix_idempotency_expiry (expires_at),
  FOREIGN KEY (actor_id) REFERENCES users(id),
  CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE stream_heads (
  topic VARCHAR(128) COLLATE utf8mb4_bin PRIMARY KEY,
  last_seq BIGINT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE stream_events (
  topic VARCHAR(128) COLLATE utf8mb4_bin NOT NULL, seq BIGINT UNSIGNED NOT NULL,
  event_id CHAR(36) NOT NULL UNIQUE, event_type VARCHAR(64) NOT NULL,
  entity_id CHAR(36) NULL, entity_version BIGINT UNSIGNED NULL,
  payload JSON NOT NULL, created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (topic,seq), KEY ix_stream_retention (created_at),
  FOREIGN KEY (topic) REFERENCES stream_heads(topic), CHECK (seq > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE outbox (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  event_id CHAR(36) NOT NULL UNIQUE,
  state ENUM('PENDING','LEASED','PUBLISHED') NOT NULL DEFAULT 'PENDING',
  attempts INT UNSIGNED NOT NULL DEFAULT 0, lease_until DATETIME(6) NULL,
  next_attempt_at DATETIME(6) NOT NULL, published_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL,
  KEY ix_outbox_pending (state,next_attempt_at,id),
  FOREIGN KEY (event_id) REFERENCES stream_events(event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
