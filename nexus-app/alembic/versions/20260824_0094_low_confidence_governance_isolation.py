"""Add disabled governance outcomes for low-confidence isolation.

Classification confidence below 0.5 is retained for audit but is not eligible
for human review, knowledge processing, or default catalog visibility.

Revision ID: 20260824_0094
Revises: 20260821_0093
Create Date: 2026-08-24
"""
from collections.abc import Sequence

from alembic import op


revision: str = "20260824_0094"
down_revision: str | None = "20260821_0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE governanceresultstatus ADD VALUE IF NOT EXISTS 'disabled'"
    )


def downgrade() -> None:
    # PostgreSQL does not safely remove enum values. The forward-only value is
    # harmless to older application code, which continues to treat it as
    # non-admissible.
    pass
