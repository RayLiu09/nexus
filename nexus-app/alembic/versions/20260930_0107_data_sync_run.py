"""Create provider-independent API data sync runs.

Revision ID: 20260930_0107
Revises: 20260929_0106
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260930_0107"
down_revision: str | None = "20260929_0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'DataSyncRunQueued'")
    json_type = sa.JSON().with_variant(JSONB, "postgresql")
    op.create_table(
        "data_sync_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("data_sync_config_id", sa.String(36), sa.ForeignKey("data_sync_config.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("adapter_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("idempotency_key", sa.String(256)),
        sa.Column("scheduled_slot", sa.DateTime(timezone=True)),
        sa.Column("external_task_id", sa.String(256)),
        sa.Column("request_id", sa.String(256)),
        sa.Column("query_snapshot", json_type, nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_cursor", sa.String(2048)),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_control_action", sa.String(16)),
        sa.Column("last_control_requested_at", sa.DateTime(timezone=True)),
        sa.Column("last_control_operator_id", sa.String(36)),
        sa.Column("external_status", sa.String(128)),
        sa.Column("status_detail", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("failure_summary", sa.String(2000)),
        sa.Column("result_summary", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("claim_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'paused', 'succeeded', 'partially_succeeded', 'failed', 'cancelled')",
            name="ck_data_sync_run_status",
        ),
        sa.UniqueConstraint("data_sync_config_id", "created_by", "idempotency_key", name="uq_data_sync_run_manual_idem"),
        sa.UniqueConstraint("data_sync_config_id", "scheduled_slot", name="uq_data_sync_run_scheduled_slot"),
    )
    op.create_index(
        "uq_data_sync_run_active_plan", "data_sync_run", ["data_sync_config_id"], unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'paused')"),
        sqlite_where=sa.text("status IN ('queued', 'running', 'paused')"),
    )
    op.create_index("ix_data_sync_run_status_queued", "data_sync_run", ["status", "queued_at"])
    op.create_index("ix_data_sync_run_provider_created", "data_sync_run", ["provider_code", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_data_sync_run_provider_created", table_name="data_sync_run")
    op.drop_index("ix_data_sync_run_status_queued", table_name="data_sync_run")
    op.drop_index("uq_data_sync_run_active_plan", table_name="data_sync_run")
    op.drop_table("data_sync_run")
