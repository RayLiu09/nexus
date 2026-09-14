"""Add description column to user_account and sync auditeventtype enum.

Revision ID: 20260911_0103
Revises: 20260911_0102

- Adds the optional `description` column on `user_account` (rendered by the
  console /users module).
- Introduces four new console-facing audit event values —
  UserCreated / UserUpdated / UserStatusChanged / UserPasswordReset —
  and re-syncs the ENTIRE ``auditeventtype`` PostgreSQL enum to the
  Python source of truth. Follows the defensive pattern established by
  20260626_0045_sync_audit_event_enum_for_ability_analysis.py so any
  historically-missed enum member is picked up here as well.
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


def upgrade() -> None:
    op.add_column(
        "user_account",
        sa.Column("description", sa.String(length=500), nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite treats the enum column as text — validation happens at the
        # SQLAlchemy layer, so nothing to sync.
        return
    # Idempotent sync of EVERY AuditEventType member (not just the four new
    # ones). Guarantees the four USER_* values land even if a prior migration
    # was skipped or the DB was seeded from an out-of-date snapshot.
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place; leaving
    # the added enum members intact is the documented convention (see e.g.
    # 20260818_0089_asset_manual_retirement_audit.py).
    op.drop_column("user_account", "description")
