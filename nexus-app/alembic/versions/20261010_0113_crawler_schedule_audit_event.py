"""Add an audit event for Crawler schedule changes.

Revision ID: 20261010_0113
Revises: 20261010_0112
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261010_0113"
down_revision: str | None = "20261010_0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'CrawlerScheduleUpdated'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing an enum value in place. The event is
    # intentionally retained on downgrade so existing audit rows remain valid.
    pass
