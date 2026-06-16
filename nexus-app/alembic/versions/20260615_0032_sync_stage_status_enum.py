"""Sync stagestatus enum with code-declared StageStatus values.

Revision ID: 20260615_0032
Revises: 20260612_0031
Create Date: 2026-06-15
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import StageStatus

revision: str = "20260615_0032"
down_revision: str | None = "20260612_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in StageStatus:
        op.execute(
            f"ALTER TYPE stagestatus ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL does not support dropping enum values safely in-place.
    pass
