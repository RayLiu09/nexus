"""job async worker fields (v2.4 §12.3.1)

Revision ID: 20260506_0004
Revises: 20260506_0003
Create Date: 2026-05-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260506_0004"
down_revision: str | None = "20260506_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.add_column(
        "job",
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column("job", sa.Column("locked_by", sa.String(128), nullable=True))
    op.add_column("job", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job", sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("job", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("job", sa.Column("idempotency_key", sa.String(256), nullable=True))
    op.add_column("job", sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("job", sa.Column("last_error_code", sa.String(128), nullable=True))
    op.add_column("job", sa.Column("last_error_message", sa.Text(), nullable=True))

    op.execute("UPDATE job SET next_run_at = created_at WHERE next_run_at IS NULL")

    op.create_index(
        "idx_job_polling",
        "job",
        ["status", "next_run_at", "priority", "created_at"],
    )
    op.create_index(
        "idx_job_lock_expiry",
        "job",
        ["status", "lock_expires_at"],
    )
    op.create_index(
        "idx_job_idempotency",
        "job",
        ["job_type", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_index("idx_job_idempotency", table_name="job")
    op.drop_index("idx_job_lock_expiry", table_name="job")
    op.drop_index("idx_job_polling", table_name="job")

    op.drop_column("job", "last_error_message")
    op.drop_column("job", "last_error_code")
    op.drop_column("job", "payload")
    op.drop_column("job", "idempotency_key")
    op.drop_column("job", "max_attempts")
    op.drop_column("job", "attempt_count")
    op.drop_column("job", "heartbeat_at")
    op.drop_column("job", "lock_expires_at")
    op.drop_column("job", "locked_at")
    op.drop_column("job", "locked_by")
    op.drop_column("job", "next_run_at")
    op.drop_column("job", "priority")
