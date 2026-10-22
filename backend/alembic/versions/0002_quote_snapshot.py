"""Freeze the quoted product and unit names, including legacy sample quotes."""
from alembic import op
revision='0002'
down_revision='0001'

def upgrade():
    op.execute('ALTER TABLE request_quotes ADD COLUMN item_snapshot JSON NULL')
    op.execute("""UPDATE request_quotes q JOIN offers o ON o.id=q.offer_id
        JOIN products p ON p.id=o.product_id JOIN units u ON u.id=p.unit_id
        SET q.item_snapshot=JSON_OBJECT('productName',p.name,'unitLabel',u.label,
            'quantityStep',CAST(p.quantity_step AS CHAR)) WHERE q.item_snapshot IS NULL""")

def downgrade():
    raise RuntimeError('Preserve quoted history; restore a backup into a new database instead.')
