"""Add description column to user_account and console user CRUD audit events.

Revision ID: 20260911_0103
Revises: 20260911_0102
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260911_0103"
down_revision: str | None = "20260911_0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_AUDIT_EVENTS = (
    AuditEventType.USER_CREATED,
    AuditEventType.USER_UPDATED,
    AuditEventType.USER_STATUS_CHANGED,
    AuditEventType.USER_PASSWORD_RESET,
)


def upgrade() -> None:
    # New optional human-readable note surfaced by the console
    # user-management module (nexus-console /users).
    op.add_column(
        "user_account",
        sa.Column("description", sa.String(length=500), nullable=True),
    )
    # PostgreSQL native enum requires ALTER TYPE ADD VALUE for each new member.
    # SQLite treats the column as text so this is a no-op there.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for member in _NEW_AUDIT_EVENTS:
            op.execute(
                f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
            )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place; leaving
    # the added enum members intact is the documented convention (see e.g.
    # 20260818_0089_asset_manual_retirement_audit.py).
    op.drop_column("user_account", "description")
