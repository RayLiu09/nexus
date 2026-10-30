"""Persist national and provincial ecommerce demonstration-base facts.

The tables are an immutable, read-only business projection. They are populated
by the deterministic sample importer and do not participate in the asset
pipeline or governance state machine.
"""

from alembic import op
import sqlalchemy as sa


revision = "20261030_0127"
down_revision = "20261029_0126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE auditeventtype "
                "ADD VALUE IF NOT EXISTS 'EcommerceDemoBasesImported'"
            )

    op.create_table(
        "ecommerce_demo_base_import",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("source_row_count", sa.Integer(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("source_declared_total", sa.Integer(), nullable=True),
        sa.Column("source_declared_pages", sa.Integer(), nullable=True),
        sa.Column("source_current_page", sa.Integer(), nullable=True),
        sa.Column("source_page_size", sa.Integer(), nullable=True),
        sa.Column("coverage_kind", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "level", "file_sha256", "parser_version",
            name="uq_ecommerce_demo_base_import_digest",
        ),
    )
    op.create_index(
        "ix_ecommerce_demo_base_import_level",
        "ecommerce_demo_base_import",
        ["level"],
    )

    op.create_table(
        "ecommerce_demo_base",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "import_id", sa.String(36),
            sa.ForeignKey("ecommerce_demo_base_import.id"),
            nullable=False,
        ),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("province_code", sa.String(16), nullable=True),
        sa.Column("province_name", sa.String(128), nullable=True),
        sa.Column("batch_code", sa.String(16), nullable=True),
        sa.Column("recognized_period", sa.String(64), nullable=False),
        sa.Column("recognized_year", sa.Integer(), nullable=True),
        sa.Column("recognized_month", sa.Integer(), nullable=True),
        sa.Column("source_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_link_enabled", sa.Boolean(), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("level IN ('national', 'provincial')", name="ck_ecommerce_demo_base_level"),
        sa.CheckConstraint(
            "batch_code IS NULL OR batch_code IN ('first', 'second', 'supplement')",
            name="ck_ecommerce_demo_base_batch",
        ),
        sa.CheckConstraint(
            "recognized_month IS NULL OR recognized_month BETWEEN 1 AND 12",
            name="ck_ecommerce_demo_base_month",
        ),
        sa.UniqueConstraint("level", "source_path", name="uq_ecommerce_demo_base_source_path"),
    )
    op.create_index(
        "ix_ecommerce_demo_base_level_province",
        "ecommerce_demo_base",
        ["level", "province_code"],
    )
    op.create_index(
        "ix_ecommerce_demo_base_level_batch",
        "ecommerce_demo_base",
        ["level", "batch_code"],
    )
    op.create_index(
        "ix_ecommerce_demo_base_level_year",
        "ecommerce_demo_base",
        ["level", "recognized_year"],
    )
    op.create_index(
        "ix_ecommerce_demo_base_import_id",
        "ecommerce_demo_base",
        ["import_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ecommerce_demo_base_import_id", table_name="ecommerce_demo_base")
    op.drop_index("ix_ecommerce_demo_base_level_year", table_name="ecommerce_demo_base")
    op.drop_index("ix_ecommerce_demo_base_level_batch", table_name="ecommerce_demo_base")
    op.drop_index("ix_ecommerce_demo_base_level_province", table_name="ecommerce_demo_base")
    op.drop_table("ecommerce_demo_base")
    op.drop_index("ix_ecommerce_demo_base_import_level", table_name="ecommerce_demo_base_import")
    op.drop_table("ecommerce_demo_base_import")
