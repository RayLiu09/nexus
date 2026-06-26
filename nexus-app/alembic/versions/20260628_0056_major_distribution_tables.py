"""Create Pipeline B major_distribution domain tables.

Revision ID: 20260628_0056
Revises: 20260628_0055
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260628_0056"
down_revision: str | None = "20260628_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "major_distribution_dataset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column(
            "asset_version_id", sa.String(36),
            sa.ForeignKey("asset_version.id"),
            nullable=False,
        ),
        sa.Column("dataset_name", sa.Text(), nullable=True),
        sa.Column("source_channel", sa.Text(), nullable=False),
        sa.Column("major_scope", sa.Text(), nullable=False),
        sa.Column("major_name", sa.Text(), nullable=True),
        sa.Column("major_code", sa.Text(), nullable=True),
        sa.Column("education_level", sa.Text(), nullable=True),
        sa.Column("year_min", sa.Integer(), nullable=True),
        sa.Column("year_max", sa.Integer(), nullable=True),
        sa.Column("province_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("placeholder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "ignored_summary_count", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("quality_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_mdd_normalized_ref_id", "major_distribution_dataset",
        ["normalized_ref_id"], unique=True,
    )
    op.create_index(
        "ix_mdd_asset_version_id", "major_distribution_dataset",
        ["asset_version_id"],
    )
    op.create_index("ix_mdd_major_code", "major_distribution_dataset", ["major_code"])
    op.create_index(
        "ix_mdd_year_range", "major_distribution_dataset", ["year_min", "year_max"],
    )

    op.create_table(
        "major_distribution_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "dataset_id", sa.String(36),
            sa.ForeignKey("major_distribution_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column("source_record_key", sa.Text(), nullable=False),
        sa.Column("source_row_no", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("year_text", sa.Text(), nullable=True),
        sa.Column("province_name", sa.Text(), nullable=False),
        sa.Column("region_scope", sa.Text(), nullable=False),
        sa.Column("major_name", sa.Text(), nullable=False),
        sa.Column("major_code", sa.Text(), nullable=False),
        sa.Column("education_level", sa.Text(), nullable=True),
        sa.Column("distribution_count", sa.Integer(), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("trace", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "dataset_id", "source_record_key",
            name="uq_mdr_dataset_source_record_key",
        ),
    )
    op.create_index("ix_mdr_dataset_id", "major_distribution_record", ["dataset_id"])
    op.create_index(
        "ix_mdr_normalized_ref_id", "major_distribution_record",
        ["normalized_ref_id"],
    )
    op.create_index("ix_mdr_major_code", "major_distribution_record", ["major_code"])
    op.create_index("ix_mdr_major_name", "major_distribution_record", ["major_name"])
    op.create_index("ix_mdr_year", "major_distribution_record", ["year"])
    op.create_index("ix_mdr_province", "major_distribution_record", ["province_name"])
    op.create_index(
        "ix_mdr_region_scope", "major_distribution_record", ["region_scope"],
    )
    op.create_index(
        "ix_mdr_education_level", "major_distribution_record", ["education_level"],
    )


def downgrade() -> None:
    op.drop_index("ix_mdr_education_level", table_name="major_distribution_record")
    op.drop_index("ix_mdr_region_scope", table_name="major_distribution_record")
    op.drop_index("ix_mdr_province", table_name="major_distribution_record")
    op.drop_index("ix_mdr_year", table_name="major_distribution_record")
    op.drop_index("ix_mdr_major_name", table_name="major_distribution_record")
    op.drop_index("ix_mdr_major_code", table_name="major_distribution_record")
    op.drop_index("ix_mdr_normalized_ref_id", table_name="major_distribution_record")
    op.drop_index("ix_mdr_dataset_id", table_name="major_distribution_record")
    op.drop_table("major_distribution_record")
    op.drop_index("ix_mdd_year_range", table_name="major_distribution_dataset")
    op.drop_index("ix_mdd_major_code", table_name="major_distribution_dataset")
    op.drop_index("ix_mdd_asset_version_id", table_name="major_distribution_dataset")
    op.drop_index("ix_mdd_normalized_ref_id", table_name="major_distribution_dataset")
    op.drop_table("major_distribution_dataset")
