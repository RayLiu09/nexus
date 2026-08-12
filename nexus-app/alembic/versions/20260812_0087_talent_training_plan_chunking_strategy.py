"""Register the talent-training-plan supplementary RAG strategy.

Revision ID: 20260812_0087
Revises: 20260812_0086
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260812_0087"
down_revision: str | None = "20260812_0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL enum values are intentionally additive. Existing chunks keep
    # their provenance and the new strategy can be deployed without a table
    # rewrite.
    op.execute(
        "ALTER TYPE chunkingstrategy "
        "ADD VALUE IF NOT EXISTS 'talent_training_plan_decompose'"
    )


def downgrade() -> None:
    # PostgreSQL cannot safely remove an enum value while historical chunk rows
    # may reference it. Downgrade is deliberately a no-op.
    pass
