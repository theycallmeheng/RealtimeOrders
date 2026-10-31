"""Remove the retired product-request and quote workflow."""
from alembic import op
from sqlalchemy import text

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _quoted_identifier(name):
    return chr(96) + name.replace(chr(96), chr(96) * 2) + chr(96)


def upgrade():
    bind = op.get_bind()

    # Orders must retain no live references before the legacy columns can be removed.
    linked = bind.execute(text(
        "SELECT COUNT(*) FROM orders "
        "WHERE source_request_id IS NOT NULL OR source_quote_id IS NOT NULL"
    )).scalar_one()
    if linked:
        raise RuntimeError(
            "Cannot retire request tables: orders still reference request/quote data."
        )

    foreign_keys = bind.execute(text(
        "SELECT DISTINCT constraint_name "
        "FROM information_schema.key_column_usage "
        "WHERE table_schema = DATABASE() AND table_name = 'orders' "
        "AND column_name IN ('source_request_id', 'source_quote_id') "
        "AND referenced_table_name IS NOT NULL"
    )).scalars().all()
    for name in foreign_keys:
        bind.exec_driver_sql(
            "ALTER TABLE orders DROP FOREIGN KEY " + _quoted_identifier(name)
        )

    # Remove unique indexes attached only to the two retired reference columns.
    indexes = bind.execute(text(
        "SELECT index_name FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = 'orders' "
        "AND column_name IN ('source_request_id', 'source_quote_id') "
        "AND non_unique = 0 GROUP BY index_name "
        "HAVING COUNT(*) = SUM(column_name IN ('source_request_id', 'source_quote_id'))"
    )).scalars().all()
    for name in indexes:
        bind.exec_driver_sql(
            "ALTER TABLE orders DROP INDEX " + _quoted_identifier(name)
        )

    op.drop_column("orders", "source_request_id")
    op.drop_column("orders", "source_quote_id")
    op.drop_table("request_status_history")
    op.drop_table("request_quotes")
    op.drop_table("product_requests")


def downgrade():
    raise RuntimeError(
        "Request data was removed intentionally. Restore the pre-migration backup "
        "into a separate database if it must be recovered."
    )
