"""Add cron scheduling columns to crawler_plan.

Revision ID: 20260807_0083
Revises: 20260806_0082
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260807_0083"
down_revision: str | None = "20260806_0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Register new audit event enum members before anything writes them.
    for member in (
        AuditEventType.CRAWLER_RUN_STARTED_BY_SCHEDULE,
        AuditEventType.CRAWLER_RUN_SKIPPED_BY_SCHEDULE,
    ):
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )

    op.add_column(
        "crawler_plan",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crawler_plan",
        sa.Column("last_fire_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crawler_plan",
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
    )

    op.create_index(
        "ix_crawler_plan_next_run",
        "crawler_plan",
        ["next_run_at"],
        postgresql_where=sa.text(
            "next_run_at IS NOT NULL "
            "AND status = 'active' "
            "AND execution_mode = 'scheduled'"
        ),
    )

    # Backfill: any active scheduled plan with a cron becomes eligible
    # for the very next scheduler tick. Once fired, the scheduler will
    # advance next_run_at via croniter.
    op.execute(
        "UPDATE crawler_plan "
        "SET next_run_at = NOW() "
        "WHERE execution_mode = 'scheduled' "
        "AND schedule_cron IS NOT NULL "
        "AND status = 'active'"
    )


def downgrade() -> None:
    op.drop_index("ix_crawler_plan_next_run", table_name="crawler_plan")
    op.drop_column("crawler_plan", "last_run_id")
    op.drop_column("crawler_plan", "last_fire_at")
    op.drop_column("crawler_plan", "next_run_at")
