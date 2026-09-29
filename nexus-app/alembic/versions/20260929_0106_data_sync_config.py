"""Create immutable API data sync plans and audit events.

Revision ID: 20260929_0106
Revises: 20260914_0105
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260929_0106"
down_revision: str | None = "20260914_0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for event in (
                "DataSyncPlanCreated",
                "DataSyncPlanPaused",
                "DataSyncPlanResumed",
                "DataSyncPlanDeleted",
            ):
                op.execute(f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{event}'")
    op.create_table(
        "data_sync_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("query_config", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'paused', 'deleted')", name="ck_data_sync_config_status"),
        sa.CheckConstraint(
            "frequency IN ('1_month', '3_months', '6_months', '9_months', '1_year')",
            name="ck_data_sync_config_frequency",
        ),
        sa.UniqueConstraint("created_by", "idempotency_key", name="uq_data_sync_config_actor_idem"),
    )
    op.create_index("ix_data_sync_config_schedule", "data_sync_config", ["status", "next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_data_sync_config_schedule", table_name="data_sync_config")
    op.drop_table("data_sync_config")
