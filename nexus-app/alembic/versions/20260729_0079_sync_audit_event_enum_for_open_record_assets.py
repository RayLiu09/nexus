"""Add the public record-assets access audit event to PostgreSQL.

The external cross-dataset record and capability-graph reads emit
``OpenRecordAssetsAccessed``.  PostgreSQL stores ``audit_log.event_type`` as
the ``auditeventtype`` enum, so the database value must be added before the
new API code can write its access audit.

Revision ID: 20260729_0079
Revises: 20260728_0078
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260729_0079"
down_revision: str | None = "20260728_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'OpenRecordAssetsAccessed'"
    )


def downgrade() -> None:
    # PostgreSQL enum values are intentionally retained on downgrade.
    return
