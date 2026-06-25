"""Sync auditeventtype enum — pick up Pipeline B B5.3 body_markdown event.

Adds `BODY_MARKDOWN_RENDERED`. Same idempotent pattern as earlier syncs.

Revision ID: 20260627_0049
Revises: 20260627_0048
Create Date: 2026-06-27
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260627_0049"
down_revision: str | None = "20260627_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    pass
