"""Replace `idx_job_lock_expiry` with a `WHERE status='running'` partial index.

Revision ID: 20260605_0021
Revises: 20260605_0020
Create Date: 2026-06-05

`recovery_sweep` is the only query that filters by lock_expires_at, and it
always pairs that with `status = 'running'`. The original composite index
`(status, lock_expires_at)` covers the query but contains entries for every
status — terminal rows (succeeded/failed/dead_lettered/cancelled) dominate
on a long-lived cluster and only inflate write cost.

Switch to a partial index analogous to the existing `idx_job_queued_polling`
(see Alembic 0005) so the index stays bounded to the in-flight set the
worker actually sweeps.
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260605_0021"
down_revision: str | None = "20260605_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("idx_job_lock_expiry", table_name="job")
    op.create_index(
        "idx_job_running_lock_expiry",
        "job",
        ["lock_expires_at"],
        postgresql_where=text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("idx_job_running_lock_expiry", table_name="job")
    op.create_index(
        "idx_job_lock_expiry",
        "job",
        ["status", "lock_expires_at"],
    )
