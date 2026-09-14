"""Add index for latest governance run lookups used by Workbench.

Revision ID: 20260914_0104
Revises: 20260911_0103
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260914_0104"
down_revision: str | None = "20260911_0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_governance_run_latest_ref",
        "ai_governance_run",
        ["normalized_ref_id", "created_at", "updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_governance_run_latest_ref", table_name="ai_governance_run")
