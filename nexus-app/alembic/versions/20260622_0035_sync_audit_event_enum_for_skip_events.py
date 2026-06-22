"""Sync auditeventtype enum — pick up KnowledgeChunkingSkipped + IndexSubmitSkipped.

Background:
- §13 (post-review index fix) adds two new AuditEventType members so the
  skip paths in `run_knowledge_chunking` / `run_index_submit` produce a
  visible audit trail. Without them, operators saw an asset transition to
  `available` with `index_admission=True` yet no IndexManifest and no
  audit event explaining the gap.
- Pattern follows the previous enum syncs (0031, 0034): idempotently
  re-issue `ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS` for every
  member of `nexus_app.enums.AuditEventType`. Safe to re-run.

Revision ID: 20260622_0035
Revises: 20260618_0034
Create Date: 2026-06-22
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260622_0035"
down_revision: str | None = "20260618_0034"
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
