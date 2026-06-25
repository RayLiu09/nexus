"""Sync auditeventtype enum — add B6 ability_analysis writer events.

Background:
- B6 introduces three writer-specific audit events:
  ABILITY_ANALYSIS_PERSISTED, ABILITY_ITEMS_PERSISTED, ABILITY_ITEMS_REJECTED.
- Pattern follows previous enum syncs (0031 / 0034 / 0035 / 0038 / 0039 /
  0040): idempotently re-issue ``ALTER TYPE auditeventtype ADD VALUE
  IF NOT EXISTS`` for every member of ``nexus_app.enums.AuditEventType``.
  Safe to re-run.

Revision ID: 20260626_0045
Revises: 20260626_0044
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260626_0045"
down_revision: str | None = "20260626_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (test) has no enum type — values are validated at the
        # SQLAlchemy layer.
        return
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL has no safe in-place DROP VALUE for enums.
    pass
