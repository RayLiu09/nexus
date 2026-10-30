"""Remove the unused import receipt and formalize the ecommerce parks table name."""

from alembic import op
import sqlalchemy as sa


revision = "20261030_0128"
down_revision = "20261030_0127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the two historical import audit events by pointing them at one
    # persisted park row before the receipt table and import_id are removed.
    op.execute(
        sa.text(
            """
            UPDATE audit_log AS audit
               SET target_type = 'ecommerce_parks',
                   target_id = COALESCE(
                       (
                           SELECT park.id
                             FROM ecommerce_demo_base AS park
                            WHERE park.import_id = audit.target_id
                            ORDER BY park.id
                            LIMIT 1
                       ),
                       audit.target_id
                   )
             WHERE audit.target_type = 'ecommerce_demo_base'
            """
        )
    )

    op.drop_index("ix_ecommerce_demo_base_import_id", table_name="ecommerce_demo_base")
    op.drop_column("ecommerce_demo_base", "import_id")
    op.drop_table("ecommerce_demo_base_import")

    for index_name in (
        "ix_ecommerce_demo_base_level_year",
        "ix_ecommerce_demo_base_level_batch",
        "ix_ecommerce_demo_base_level_province",
    ):
        op.drop_index(index_name, table_name="ecommerce_demo_base")
    op.rename_table("ecommerce_demo_base", "ecommerce_parks")

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                "ALTER TABLE ecommerce_parks "
                "RENAME CONSTRAINT ck_ecommerce_demo_base_level TO ck_ecommerce_parks_level"
            )
        )
        connection.execute(
            sa.text(
                "ALTER TABLE ecommerce_parks "
                "RENAME CONSTRAINT ck_ecommerce_demo_base_batch TO ck_ecommerce_parks_batch"
            )
        )
        connection.execute(
            sa.text(
                "ALTER TABLE ecommerce_parks "
                "RENAME CONSTRAINT ck_ecommerce_demo_base_month TO ck_ecommerce_parks_month"
            )
        )
        connection.execute(
            sa.text(
                "ALTER TABLE ecommerce_parks "
                "RENAME CONSTRAINT uq_ecommerce_demo_base_source_path "
                "TO uq_ecommerce_parks_source_path"
            )
        )

    op.create_index(
        "ix_ecommerce_parks_level_province", "ecommerce_parks", ["level", "province_code"]
    )
    op.create_index(
        "ix_ecommerce_parks_level_batch", "ecommerce_parks", ["level", "batch_code"]
    )
    op.create_index(
        "ix_ecommerce_parks_level_year", "ecommerce_parks", ["level", "recognized_year"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "ecommerce_parks cleanup is irreversible: import receipts and import_id were removed"
    )
