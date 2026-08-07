"""Add schedule_paused flag to crawler_plan.

Revision ID: 20260807_0084
Revises: 20260807_0083
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260807_0084"
down_revision: str | None = "20260807_0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in (
        AuditEventType.CRAWLER_SCHEDULE_PAUSED,
        AuditEventType.CRAWLER_SCHEDULE_RESUMED,
    ):
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )

    op.add_column(
        "crawler_plan",
        sa.Column(
            "schedule_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("crawler_plan", "schedule_paused")
