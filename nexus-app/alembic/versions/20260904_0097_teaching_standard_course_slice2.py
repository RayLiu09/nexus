"""Create teaching-standard course Slice 2 projection table.

Revision ID: 20260904_0097
Revises: 20260904_0096
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260904_0097"
down_revision: str | None = "20260904_0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teaching_standard_course",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "library_id",
            sa.String(36),
            sa.ForeignKey("teaching_standard_library.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", sa.String(128), nullable=False),
        sa.Column("standard_course_name", sa.Text(), nullable=False),
        sa.Column("course_type", sa.String(24), nullable=False),
        sa.Column("suggested_total_hours", sa.Integer(), nullable=True),
        sa.Column("suggested_practice_hours", sa.Integer(), nullable=True),
        sa.Column("suggested_hours_range", sa.JSON(), nullable=True),
        sa.Column("hours_setting_basis", sa.Text(), nullable=True),
        sa.Column("typical_work_task_description", sa.Text(), nullable=True),
        sa.Column("teaching_content_requirement", sa.Text(), nullable=True),
        sa.Column("knowledge_tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("skill_tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("tool_tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("literacy_tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("match_keywords", sa.Text(), nullable=True),
        sa.Column("match_text", sa.Text(), nullable=True),
        sa.Column("source_standard", sa.Text(), nullable=True),
        sa.Column("source_section", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Text(), nullable=True),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(128), nullable=False),
        sa.Column("evidence_bindings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("extractor_version", sa.String(128), nullable=False),
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
            "course_type IN ('foundation', 'core', 'extension')",
            name="ck_tsc_course_type",
        ),
        sa.UniqueConstraint(
            "library_id",
            "course_type",
            "standard_course_name",
            name="uq_tsc_library_type_name",
        ),
        sa.UniqueConstraint("library_id", "course_id", name="uq_tsc_library_course_id"),
    )
    op.create_index("ix_tsc_library_id", "teaching_standard_course", ["library_id"])
    op.create_index("ix_tsc_course_type", "teaching_standard_course", ["course_type"])
    op.create_index(
        "ix_tsc_standard_course_name",
        "teaching_standard_course",
        ["standard_course_name"],
    )


def downgrade() -> None:
    for name in (
        "ix_tsc_standard_course_name",
        "ix_tsc_course_type",
        "ix_tsc_library_id",
    ):
        op.drop_index(name, table_name="teaching_standard_course")
    op.drop_table("teaching_standard_course")
