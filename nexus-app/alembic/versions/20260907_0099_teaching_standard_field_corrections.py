"""Correct teaching-standard identity, classification, and tag storage.

Revision ID: 20260907_0099
Revises: 20260904_0098
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260907_0099"
down_revision: str | None = "20260904_0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TAG_COLUMNS = (
    "knowledge_tags",
    "skill_tags",
    "tool_tags",
    "literacy_tags",
)


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tsl_standard_id")
    op.execute(
        "ALTER TABLE teaching_standard_library "
        "DROP CONSTRAINT IF EXISTS uq_tsl_standard_hash"
    )
    op.execute(
        "ALTER TABLE teaching_standard_library DROP COLUMN IF EXISTS standard_id"
    )
    for column in _TAG_COLUMNS:
        op.execute(
            f"ALTER TABLE teaching_standard_course "
            f"ALTER COLUMN {column} DROP DEFAULT"
        )
        op.execute(
            f"ALTER TABLE teaching_standard_course "
            f"ALTER COLUMN {column} TYPE JSONB USING {column}::JSONB"
        )
        op.execute(
            f"ALTER TABLE teaching_standard_course "
            f"ALTER COLUMN {column} SET DEFAULT '[]'::JSONB"
        )


def downgrade() -> None:
    for column in _TAG_COLUMNS:
        op.execute(
            f"ALTER TABLE teaching_standard_course "
            f"ALTER COLUMN {column} DROP DEFAULT"
        )
        op.execute(
            f"ALTER TABLE teaching_standard_course "
            f"ALTER COLUMN {column} TYPE JSON USING {column}::JSON"
        )
        op.execute(
            f"ALTER TABLE teaching_standard_course "
            f"ALTER COLUMN {column} SET DEFAULT '[]'::JSON"
        )
    op.execute("ALTER TABLE teaching_standard_library ADD COLUMN standard_id TEXT")
    op.create_unique_constraint(
        "uq_tsl_standard_hash",
        "teaching_standard_library",
        ["standard_id", "hash_digest"],
    )
    op.create_index(
        "ix_tsl_standard_id",
        "teaching_standard_library",
        ["standard_id"],
    )
