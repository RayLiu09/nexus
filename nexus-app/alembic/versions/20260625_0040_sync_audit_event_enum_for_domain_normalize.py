"""Sync auditeventtype enum — pick up Pipeline B Phase 0 domain_normalize events.

Background:
- Phase 0 (B4 / B6 parallel contract freeze prep) adds two dispatcher-level
  audit events: `DOMAIN_NORMALIZE_COMPLETED` and `DOMAIN_NORMALIZE_FAILED`.
  Writer-specific events (JOB_DEMAND_* / ABILITY_*) ship with the B4 / B6
  worktrees in separate revisions; this revision only covers the shared
  dispatcher.
- Pattern follows previous enum syncs (0031 / 0034 / 0035 / 0038 / 0039):
  idempotently re-issue ``ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS``
  for every member of ``nexus_app.enums.AuditEventType``. Safe to re-run, and
  safe to land before / after B4 / B6 add their own writer-specific events
  (each will re-run the same idempotent loop).

Revision ID: 20260625_0040
Revises: 20260625_0039
Create Date: 2026-06-25
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260625_0040"
down_revision: str | None = "20260625_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL has no safe in-place DROP VALUE for enums.
    pass
