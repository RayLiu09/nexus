"""partial index on queued jobs for worker polling (v2.4 §12.3.2)

Revision ID: 20260506_0005
Revises: 20260506_0004
Create Date: 2026-05-06
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260506_0005"
down_revision: str | None = "20260506_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Partial index covering only QUEUED rows — the set the worker polls.
    # Stays tiny because completed/failed/dead-lettered jobs fall out automatically.
    op.create_index(
        "idx_job_queued_polling",
        "job",
        ["next_run_at", "priority", "created_at"],
        postgresql_where=text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("idx_job_queued_polling", table_name="job")
