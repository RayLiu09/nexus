"""Sync auditeventtype enum — pick up StructuredParseCompleted (Pipeline B B1.3).

Background:
- B1.3 (Pipeline B worker integration) adds the `STRUCTURED_PARSE_COMPLETED`
  audit event so successful xlsx / (future) csv structured_parse stages
  produce a visible audit trail. Failures continue to use the existing
  `PIPELINE_FAILED` event with `error_code="structured_parse_failed"`.
- Pattern follows the previous enum syncs (0031 / 0034 / 0035): idempotently
  re-issue `ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS` for every
  member of `nexus_app.enums.AuditEventType`. Safe to re-run.

Revision ID: 20260624_0038
Revises: 20260622_0037
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260624_0038"
down_revision: str | None = "20260622_0037"
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
