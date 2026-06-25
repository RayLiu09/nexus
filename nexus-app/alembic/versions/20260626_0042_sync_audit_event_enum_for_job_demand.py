"""Sync auditeventtype enum — pick up B4 writer-specific events.

Adds:
  - JOB_DEMAND_DATASET_PERSISTED ('JobDemandDatasetPersisted')
  - JOB_DEMAND_RECORDS_PERSISTED ('JobDemandRecordsPersisted')

Follows the same idempotent pattern as 0031 / 0034 / 0035 / 0038 / 0039 / 0040:
re-issue `ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS` for every member
of `nexus_app.enums.AuditEventType`. Safe to re-run, and safe to land before
/ after B6 adds its own writer-specific events (each will re-run the same
idempotent loop).

Revision ID: 20260626_0042
Revises: 20260626_0041
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260626_0042"
down_revision: str | None = "20260626_0041"
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
