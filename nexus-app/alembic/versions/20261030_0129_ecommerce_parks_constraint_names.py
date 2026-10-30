"""Align inherited PostgreSQL constraint names with the ecommerce parks table."""

from alembic import op
import sqlalchemy as sa


revision = "20261030_0129"
down_revision = "20261030_0128"
branch_labels = None
depends_on = None


_RENAMES = (
    ("ecommerce_demo_base_pkey", "ecommerce_parks_pkey"),
    ("ecommerce_demo_base_id_not_null", "ecommerce_parks_id_not_null"),
    ("ecommerce_demo_base_level_not_null", "ecommerce_parks_level_not_null"),
    ("ecommerce_demo_base_source_path_not_null", "ecommerce_parks_source_path_not_null"),
    ("ecommerce_demo_base_title_not_null", "ecommerce_parks_title_not_null"),
    ("ecommerce_demo_base_recognized_period_not_null", "ecommerce_parks_recognized_period_not_null"),
    ("ecommerce_demo_base_source_link_enabled_not_null", "ecommerce_parks_source_link_enabled_not_null"),
    ("ecommerce_demo_base_source_order_not_null", "ecommerce_parks_source_order_not_null"),
    ("ecommerce_demo_base_source_locator_not_null", "ecommerce_parks_source_locator_not_null"),
    ("ecommerce_demo_base_source_payload_not_null", "ecommerce_parks_source_payload_not_null"),
    ("ecommerce_demo_base_created_at_not_null", "ecommerce_parks_created_at_not_null"),
    ("ecommerce_demo_base_updated_at_not_null", "ecommerce_parks_updated_at_not_null"),
)


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    for old_name, new_name in _RENAMES:
        exists = connection.scalar(
            sa.text(
                """
                SELECT 1
                  FROM pg_constraint
                 WHERE conrelid = 'ecommerce_parks'::regclass
                   AND conname = :old_name
                """
            ),
            {"old_name": old_name},
        )
        if exists:
            # Names are static migration constants, so interpolating them here
            # avoids relying on bind parameters inside an anonymous DO block.
            connection.exec_driver_sql(
                f'ALTER TABLE ecommerce_parks RENAME CONSTRAINT "{old_name}" TO "{new_name}"'
            )


def downgrade() -> None:
    raise RuntimeError("ecommerce parks constraint renames are intentionally irreversible")
