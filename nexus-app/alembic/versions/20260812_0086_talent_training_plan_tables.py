"""Create Pipeline A talent training plan projection tables.

Revision ID: 20260812_0086
Revises: 20260807_0085
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0086"
down_revision: str | None = "20260807_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "talent_training_plan",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_ref_id", sa.String(36), sa.ForeignKey("normalized_asset_ref.id"), nullable=False),
        sa.Column("asset_version_id", sa.String(36), sa.ForeignKey("asset_version.id"), nullable=False),
        sa.Column("domain_profile", sa.String(64), nullable=False),
        sa.Column("institution_name", sa.Text(), nullable=True),
        sa.Column("major_name", sa.Text(), nullable=False),
        sa.Column("major_code", sa.Text(), nullable=True),
        sa.Column("education_level", sa.Text(), nullable=True),
        sa.Column("study_duration", sa.Text(), nullable=True),
        sa.Column("training_goal", sa.Text(), nullable=True),
        sa.Column("training_specification", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("career_orientation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("certificates", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("normalized_ref_id", name="uq_ttp_normalized_ref"),
    )
    for name, column in (("ix_ttp_asset_version_id", "asset_version_id"), ("ix_ttp_institution_name", "institution_name"), ("ix_ttp_major_code", "major_code"), ("ix_ttp_major_name", "major_name"), ("ix_ttp_education_level", "education_level")):
        op.create_index(name, "talent_training_plan", [column])

    op.create_table(
        "talent_training_plan_course",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("talent_training_plan.id", ondelete="CASCADE"), nullable=False),
        sa.Column("normalized_ref_id", sa.String(36), sa.ForeignKey("normalized_asset_ref.id"), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("course_name", sa.Text(), nullable=False),
        sa.Column("course_code", sa.Text(), nullable=True),
        sa.Column("curriculum_group", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("course_type", sa.Text(), nullable=False, server_default="course"),
        sa.Column("course_objective", sa.Text(), nullable=True),
        sa.Column("course_content", sa.Text(), nullable=True),
        sa.Column("skill_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("knowledge_topics", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("metadata_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("plan_id", "item_index", name="uq_ttpc_plan_item_index"),
    )
    op.create_index("ix_ttpc_plan_id", "talent_training_plan_course", ["plan_id"])
    op.create_index("ix_ttpc_course_name", "talent_training_plan_course", ["course_name"])
    op.create_index("ix_ttpc_curriculum_group", "talent_training_plan_course", ["curriculum_group"])


def downgrade() -> None:
    for name in ("ix_ttpc_curriculum_group", "ix_ttpc_course_name", "ix_ttpc_plan_id"):
        op.drop_index(name, table_name="talent_training_plan_course")
    op.drop_table("talent_training_plan_course")
    for name in ("ix_ttp_education_level", "ix_ttp_major_name", "ix_ttp_major_code", "ix_ttp_institution_name", "ix_ttp_asset_version_id"):
        op.drop_index(name, table_name="talent_training_plan")
    op.drop_table("talent_training_plan")
