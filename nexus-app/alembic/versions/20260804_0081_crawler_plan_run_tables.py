"""Create crawler plan and run tables.

Revision ID: 20260804_0081
Revises: 20260730_0080
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260804_0081"
down_revision: str | None = "20260730_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )

    op.create_table(
        "crawler_plan",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("template_code", sa.String(length=80), nullable=True),
        sa.Column("template_version", sa.String(length=80), nullable=True),
        sa.Column("region_code", sa.String(length=64), nullable=True),
        sa.Column("region_name", sa.String(length=128), nullable=True),
        sa.Column("topic_keywords", sa.JSON(), nullable=False),
        sa.Column("content_goals", sa.JSON(), nullable=False),
        sa.Column("classification_hints", sa.JSON(), nullable=False),
        sa.Column("target_sites", sa.JSON(), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("schedule_cron", sa.String(length=128), nullable=True),
        sa.Column("crawl_policy", sa.JSON(), nullable=False),
        sa.Column("pipeline_policy", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "execution_mode IN ('run_once', 'scheduled')",
            name="ck_crawler_plan_execution_mode",
        ),
        sa.CheckConstraint("mode IN ('quick_start', 'custom')", name="ck_crawler_plan_mode"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'archived')",
            name="ck_crawler_plan_status",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_source.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawler_plan_region", "crawler_plan", ["region_code"])
    op.create_index("ix_crawler_plan_status", "crawler_plan", ["status"])

    op.create_table(
        "crawler_run",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("template_code", sa.String(length=80), nullable=True),
        sa.Column("template_config_hash", sa.String(length=128), nullable=True),
        sa.Column("region_sites_config_hash", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial_failed', 'failed')",
            name="ck_crawler_run_status",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["crawler_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawler_run_plan", "crawler_run", ["plan_id"])
    op.create_index("ix_crawler_run_started_at", "crawler_run", ["started_at"])
    op.create_index("ix_crawler_run_status", "crawler_run", ["status"])


def downgrade() -> None:
    op.drop_index("ix_crawler_run_status", table_name="crawler_run")
    op.drop_index("ix_crawler_run_started_at", table_name="crawler_run")
    op.drop_index("ix_crawler_run_plan", table_name="crawler_run")
    op.drop_table("crawler_run")
    op.drop_index("ix_crawler_plan_status", table_name="crawler_plan")
    op.drop_index("ix_crawler_plan_region", table_name="crawler_plan")
    op.drop_table("crawler_plan")
