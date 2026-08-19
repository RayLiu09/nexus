"""Add audit events for manual asset archive and deletion.

Revision ID: 20260818_0089
Revises: 20260818_0088
"""
from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260818_0089"
down_revision: str | None = "20260818_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in (AuditEventType.ASSET_ARCHIVED, AuditEventType.ASSET_DELETED):
        op.execute(f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place.
    pass
