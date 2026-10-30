"""Allow uploaded files or HTTPS URLs as product images."""
from alembic import op
from sqlalchemy import inspect

revision = '0007'
down_revision = '0006'


def upgrade():
    bind=op.get_bind()
    primary=inspect(bind).get_pk_constraint('product_images').get('constrained_columns') or []
    if primary == ['product_id','asset_id']:
        op.execute('ALTER TABLE product_images DROP PRIMARY KEY')
    elif primary not in ([],['product_id','position']):
        raise RuntimeError('Unexpected product_images primary key; inspect before migrating.')

    columns={column['name']:column for column in inspect(bind).get_columns('product_images')}
    if not columns['asset_id']['nullable']:
        op.execute('ALTER TABLE product_images MODIFY asset_id CHAR(36) NULL')
    if 'source_url' not in columns:
        op.execute('ALTER TABLE product_images ADD source_url VARCHAR(2048) NULL AFTER asset_id')

    primary=inspect(bind).get_pk_constraint('product_images').get('constrained_columns') or []
    if not primary:
        op.execute('ALTER TABLE product_images ADD PRIMARY KEY (product_id,position)')
    elif primary != ['product_id','position']:
        raise RuntimeError('Could not establish product image ordering key.')

    indexes={index['name'] for index in inspect(bind).get_indexes('product_images')}
    if 'uq_product_image_position' in indexes:
        op.execute('ALTER TABLE product_images DROP INDEX uq_product_image_position')
    if 'uq_product_image_asset' not in indexes:
        op.execute('ALTER TABLE product_images ADD UNIQUE KEY uq_product_image_asset (product_id,asset_id)')

    checks={constraint.get('name') for constraint in inspect(bind).get_check_constraints('product_images')}
    if 'ck_product_image_source' not in checks:
        op.execute("""ALTER TABLE product_images
            ADD CONSTRAINT ck_product_image_source
            CHECK ((asset_id IS NOT NULL AND source_url IS NULL)
                OR (asset_id IS NULL AND source_url IS NOT NULL))""")


def downgrade():
    raise RuntimeError('Giữ URL ảnh đã lưu; phục hồi backup vào database mới nếu cần quay lại.')
