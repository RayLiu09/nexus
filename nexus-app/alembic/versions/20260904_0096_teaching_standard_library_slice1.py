"""Create teaching-standard library Slice 1 fact projection tables.

Revision ID: 20260904_0096
Revises: 20260825_0095
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260904_0096"
down_revision: str | None = "20260825_0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'")

    op.create_table(
        "teaching_standard_library",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id",
            sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column(
            "asset_version_id", sa.String(36), sa.ForeignKey("asset_version.id"), nullable=False
        ),
        sa.Column("domain_profile", sa.String(64), nullable=False),
        sa.Column("standard_id", sa.Text(), nullable=True),
        sa.Column("standard_title", sa.Text(), nullable=True),
        sa.Column("major_code", sa.Text(), nullable=True),
        sa.Column("major_name", sa.Text(), nullable=True),
        sa.Column("education_level", sa.Text(), nullable=True),
        sa.Column("major_category_code", sa.Text(), nullable=True),
        sa.Column("major_category_name", sa.Text(), nullable=True),
        sa.Column("major_class_code", sa.Text(), nullable=True),
        sa.Column("major_class_name", sa.Text(), nullable=True),
        sa.Column("basic_study_years", sa.Text(), nullable=True),
        sa.Column("training_goal_summary", sa.Text(), nullable=True),
        sa.Column("course_structures", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("original_from", sa.Text(), nullable=True),
        sa.Column("hash_digest", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="review"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("source_evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('review', 'active', 'superseded')", name="ck_tsl_status"),
        sa.UniqueConstraint("normalized_ref_id", name="uq_tsl_normalized_ref"),
        sa.UniqueConstraint("standard_id", "hash_digest", name="uq_tsl_standard_hash"),
    )
    for name, column in (
        ("ix_tsl_asset_version_id", "asset_version_id"),
        ("ix_tsl_standard_id", "standard_id"),
        ("ix_tsl_major_code", "major_code"),
        ("ix_tsl_major_name", "major_name"),
        ("ix_tsl_status", "status"),
    ):
        op.create_index(name, "teaching_standard_library", [column])

    op.create_table(
        "teaching_standard_occupation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "library_id",
            sa.String(36),
            sa.ForeignKey("teaching_standard_library.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension_type", sa.String(32), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("locator", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "dimension_type IN ('applied_industry', 'occupation_type', 'primary_position', 'certificate_type')",
            name="ck_tso_dimension_type",
        ),
        sa.UniqueConstraint(
            "library_id", "dimension_type", "item_index", name="uq_tso_library_dimension_item"
        ),
    )
    op.create_index("ix_tso_library_id", "teaching_standard_occupation", ["library_id"])
    op.create_index("ix_tso_dimension_type", "teaching_standard_occupation", ["dimension_type"])

    op.create_table(
        "teaching_standard_rule",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "library_id",
            sa.String(36),
            sa.ForeignKey("teaching_standard_library.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_type", sa.String(48), nullable=False),
        sa.Column("comparator", sa.String(8), nullable=False),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(24), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("locator", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "rule_type IN ('total_hours', 'public_foundation_ratio', 'professional_course_ratio', 'practice_ratio', 'elective_ratio', 'internship_months')",
            name="ck_tsr_rule_type",
        ),
        sa.CheckConstraint("comparator IN ('>=', '<=', '=', 'range')", name="ck_tsr_comparator"),
    )
    op.create_index("ix_tsr_library_id", "teaching_standard_rule", ["library_id"])
    op.create_index("ix_tsr_rule_type", "teaching_standard_rule", ["rule_type"])


def downgrade() -> None:
    for name in ("ix_tsr_rule_type", "ix_tsr_library_id"):
        op.drop_index(name, table_name="teaching_standard_rule")
    op.drop_table("teaching_standard_rule")
    for name in ("ix_tso_dimension_type", "ix_tso_library_id"):
        op.drop_index(name, table_name="teaching_standard_occupation")
    op.drop_table("teaching_standard_occupation")
    for name in (
        "ix_tsl_status",
        "ix_tsl_major_name",
        "ix_tsl_major_code",
        "ix_tsl_standard_id",
        "ix_tsl_asset_version_id",
    ):
        op.drop_index(name, table_name="teaching_standard_library")
    op.drop_table("teaching_standard_library")
