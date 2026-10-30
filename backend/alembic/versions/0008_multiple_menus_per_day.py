"""Allow multiple daily menus while keeping each sale window distinct."""
from alembic import op
from sqlalchemy import inspect, text

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    indexes = inspect(bind).get_indexes('daily_menus')
    unique_sale_date = [
        index for index in indexes
        if index.get('unique') and index.get('column_names') == ['sale_date']
    ]
    if len(unique_sale_date) != 1:
        raise RuntimeError('Expected one unique daily_menus.sale_date index; inspect the schema before upgrading.')
    op.drop_index(unique_sale_date[0]['name'], table_name='daily_menus')


def downgrade():
    bind = op.get_bind()
    duplicate = bind.execute(text(
        'SELECT sale_date FROM daily_menus GROUP BY sale_date HAVING COUNT(*) > 1 LIMIT 1'
    )).first()
    if duplicate:
        raise RuntimeError('Cannot restore one-menu-per-day while duplicate dates exist; consolidate menus first.')
    indexes = inspect(bind).get_indexes('daily_menus')
    if any(index.get('unique') and index.get('column_names') == ['sale_date'] for index in indexes):
        return
    op.create_index('sale_date', 'daily_menus', ['sale_date'], unique=True)
