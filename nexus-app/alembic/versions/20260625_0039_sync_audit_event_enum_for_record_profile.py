"""Sync auditeventtype enum — pick up Pipeline B B2.3 profile_detect events.

Background:
- B2.3 (Pipeline B profile_detect worker integration) adds two new audit
  events: `RECORD_PROFILE_DETECTED` (every successful detection) and
  `RECORD_PROFILE_REVIEW_REQUIRED` (low-confidence / candidate / generic
  fallback record_types). High-confidence detections only emit the first;
  candidates emit BOTH so review-queue UIs can disjoin on the second.
- Pattern follows the previous enum syncs (0031 / 0034 / 0035 / 0038):
  idempotently re-issue ``ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS``
  for every member of ``nexus_app.enums.AuditEventType``. Safe to re-run.

Revision ID: 20260625_0039
Revises: 20260624_0038
Create Date: 2026-06-25
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260625_0039"
down_revision: str | None = "20260624_0038"
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
