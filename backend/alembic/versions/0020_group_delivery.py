"""Use one active distance-based delivery policy per customer group."""
from alembic import op

revision = '0020'
down_revision = '0019'


def upgrade():
    # Keep old zone references available to audit/history. New records need no zone.
    for table in ('addresses', 'pickup_slots', 'delivery_policies'):
        op.execute(f"ALTER TABLE {table} MODIFY zone_id CHAR(36) NULL")

    op.execute("""
        UPDATE delivery_policies AS policy
        JOIN (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY group_id ORDER BY distance_enabled DESC, version DESC, id
            ) AS policy_rank
            FROM delivery_policies
            WHERE method='INDIVIDUAL' AND active=TRUE
        ) AS ranked ON ranked.id=policy.id
        SET policy.active=FALSE, policy.version=policy.version+1
        WHERE ranked.policy_rank>1
    """)
    op.execute("""
        ALTER TABLE delivery_policies
        ADD active_individual_group CHAR(36) GENERATED ALWAYS AS (
            CASE WHEN method='INDIVIDUAL' AND active=TRUE THEN group_id ELSE NULL END
        ) VIRTUAL,
        ADD UNIQUE KEY uq_active_individual_group (active_individual_group)
    """)


def downgrade():
    raise RuntimeError('Restore the pre-upgrade backup into a new database.')
