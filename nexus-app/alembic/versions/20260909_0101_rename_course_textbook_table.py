"""Rename the course-textbook master projection table in place.

Revision ID: 20260909_0101
Revises: 20260907_0100
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260909_0101"
down_revision: str | None = "20260907_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("task_outline_profile", "course_textbook")
    op.execute(
        "ALTER TABLE course_textbook "
        "RENAME CONSTRAINT uq_task_outline_profile_ref_asset_profile "
        "TO uq_course_textbook_ref_asset_profile"
    )
    op.execute(
        "ALTER INDEX ix_task_outline_profile_normalized_ref_id "
        "RENAME TO ix_course_textbook_normalized_ref_id"
    )
    op.execute(
        "ALTER INDEX ix_task_outline_profile_asset_version_id "
        "RENAME TO ix_course_textbook_asset_version_id"
    )
    op.execute(
        "ALTER INDEX ix_task_outline_profile_processing "
        "RENAME TO ix_course_textbook_processing"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX ix_course_textbook_processing "
        "RENAME TO ix_task_outline_profile_processing"
    )
    op.execute(
        "ALTER INDEX ix_course_textbook_asset_version_id "
        "RENAME TO ix_task_outline_profile_asset_version_id"
    )
    op.execute(
        "ALTER INDEX ix_course_textbook_normalized_ref_id "
        "RENAME TO ix_task_outline_profile_normalized_ref_id"
    )
    op.execute(
        "ALTER TABLE course_textbook "
        "RENAME CONSTRAINT uq_course_textbook_ref_asset_profile "
        "TO uq_task_outline_profile_ref_asset_profile"
    )
    op.rename_table("course_textbook", "task_outline_profile")
