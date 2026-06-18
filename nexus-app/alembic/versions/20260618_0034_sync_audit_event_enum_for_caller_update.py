"""Sync auditeventtype enum — pick up ApiCallerUpdated and any other code
values added after migration 0031.

Background:
- Commit 6c6e76d ("feat(console): add API caller expiry management, key
  display, and audit pagination") added `API_CALLER_UPDATED = "ApiCallerUpdated"`
  to `nexus_app.enums.AuditEventType` but did not ship a matching ALTER TYPE
  migration. As a result, `PATCH /internal/v1/api-callers/{id}` (and any
  other handler that emits this event) fails on PostgreSQL with:
    invalid input value for enum auditeventtype: "ApiCallerUpdated"
- Pattern follows migration 0031: idempotently re-issue ADD VALUE IF NOT
  EXISTS for every member, so this migration is safe to re-run and to apply
  on any state of the enum that has drifted behind the Python definition.

Revision ID: 20260618_0034
Revises: 20260616_0033
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260618_0034"
down_revision: str | None = "20260616_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL has no safe in-place DROP VALUE for enums; matches 0031.
    pass
