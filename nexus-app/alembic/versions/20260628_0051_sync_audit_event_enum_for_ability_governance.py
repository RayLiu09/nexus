"""Sync auditeventtype enum — pick up Pipeline B B7 ability governance event.

Adds `ABILITY_ANALYSIS_GOVERNED`. Same idempotent pattern as earlier syncs.

Revision ID: 20260628_0051
Revises: 20260627_0050
Create Date: 2026-06-28
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260628_0051"
down_revision: str | None = "20260627_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    pass
