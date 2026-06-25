"""Create Pipeline B B4 job-demand domain tables.

Tables (frozen by `docs/pipeline_b_contract_freeze.md §5.1 / §5.2 / §5.3`):
  - job_demand_dataset
  - job_demand_record (cascade delete from dataset)
  - job_demand_requirement_item (B5-owned writes; B4 only creates the schema)

Index / constraint names mirror the SQLAlchemy `__table_args__` exactly so
`alembic check` stays clean.

`job_demand_requirement_item.rules_version_id` is a plain `String(36)` here —
the `ai_analysis_rules` table is owned by B5 and ships in a later migration
which will attach the FK constraint.

Revision ID: 20260626_0041
Revises: 20260625_0040
Create Date: 2026-06-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0041"
down_revision: str | None = "20260625_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ----- job_demand_dataset ------------------------------------------------
    op.create_table(
        "job_demand_dataset",
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
        sa.Column("major_name", sa.Text(), nullable=True),
        sa.Column("industry_name", sa.Text(), nullable=True),
        sa.Column("source_channel", sa.Text(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column(
            "quality_summary", sa.JSON(), nullable=False, server_default="{}",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # `ix_jdd_normalized_ref_id` is UNIQUE — see SQLAlchemy model + §三.3
    # (one dataset per normalized_ref, re-runs delete-then-insert).
    op.create_index(
        "ix_jdd_normalized_ref_id", "job_demand_dataset",
        ["normalized_ref_id"], unique=True,
    )
    op.create_index(
        "ix_jdd_asset_version_id", "job_demand_dataset", ["asset_version_id"],
    )
    op.create_index("ix_jdd_major", "job_demand_dataset", ["major_name"])
    op.create_index("ix_jdd_industry", "job_demand_dataset", ["industry_name"])

    # ----- job_demand_record -------------------------------------------------
    op.create_table(
        "job_demand_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "dataset_id", sa.String(36),
            sa.ForeignKey("job_demand_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column("source_record_key", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_platform", sa.Text(), nullable=True),
        sa.Column("source_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=False),
        sa.Column("employment_type", sa.Text(), nullable=True),
        sa.Column("job_function_category", sa.Text(), nullable=True),
        sa.Column("job_count", sa.Integer(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("salary_min", sa.Numeric(), nullable=True),
        sa.Column("salary_max", sa.Numeric(), nullable=True),
        sa.Column("salary_text", sa.Text(), nullable=True),
        sa.Column("experience_requirement", sa.Text(), nullable=True),
        sa.Column("education_requirement", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("company_address", sa.Text(), nullable=True),
        sa.Column("enterprise_size", sa.Text(), nullable=True),
        sa.Column("industry_name", sa.Text(), nullable=True),
        sa.Column("job_skill_text", sa.Text(), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("responsibility_text", sa.Text(), nullable=True),
        sa.Column("requirement_text", sa.Text(), nullable=True),
        sa.Column("record_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "quality_flags", sa.JSON(), nullable=False, server_default="{}",
        ),
        sa.Column(
            "trace", sa.JSON(), nullable=False, server_default="{}",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "dataset_id", "record_fingerprint",
            name="uq_jdr_dataset_fingerprint",
        ),
    )
    op.create_index("ix_jdr_dataset_id", "job_demand_record", ["dataset_id"])
    op.create_index(
        "ix_jdr_normalized_ref_id", "job_demand_record", ["normalized_ref_id"],
    )
    op.create_index("ix_jdr_city", "job_demand_record", ["city"])
    op.create_index("ix_jdr_industry", "job_demand_record", ["industry_name"])
    op.create_index(
        "ix_jdr_enterprise_size", "job_demand_record", ["enterprise_size"],
    )
    op.create_index(
        "ix_jdr_employment_type", "job_demand_record", ["employment_type"],
    )

    # ----- job_demand_requirement_item --------------------------------------
    op.create_table(
        "job_demand_requirement_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "record_id", sa.String(36),
            sa.ForeignKey("job_demand_record.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id", sa.String(36),
            sa.ForeignKey("job_demand_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("normalized_name", sa.Text(), nullable=True),
        sa.Column("taxonomy_code", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=True),
        sa.Column("evidence_field", sa.Text(), nullable=True),
        # FK to ai_prompt_profile is logically B5-owned; keep this as a plain
        # column so the table can be built before B5 migrations land.
        sa.Column("prompt_template_id", sa.String(36), nullable=True),
        # FK to ai_analysis_rules will be attached by a B5 follow-up migration.
        sa.Column("rules_version_id", sa.String(36), nullable=True),
        sa.Column("ai_model_alias", sa.Text(), nullable=True),
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
        "ix_jdri_record_id", "job_demand_requirement_item", ["record_id"],
    )
    op.create_index(
        "ix_jdri_dataset_id", "job_demand_requirement_item", ["dataset_id"],
    )
    op.create_index(
        "ix_jdri_item_type", "job_demand_requirement_item", ["item_type"],
    )
    op.create_index(
        "ix_jdri_rules_version_id", "job_demand_requirement_item",
        ["rules_version_id"],
    )


def downgrade() -> None:
    # Reverse order so FK targets exist when each child table is dropped.
    op.drop_table("job_demand_requirement_item")
    op.drop_table("job_demand_record")
    op.drop_table("job_demand_dataset")
