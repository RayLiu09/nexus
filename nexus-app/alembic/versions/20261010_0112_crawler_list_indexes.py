"""Add indexes used by paginated Crawler Console lists.

Revision ID: 20261010_0112
Revises: 20261008_0111
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261010_0112"
down_revision: str | None = "20261008_0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_crawler_plan_created_at",
        "crawler_plan",
        ["created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "ix_crawler_run_plan_started_at",
        "crawler_run",
        ["plan_id", "started_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_crawler_run_plan_started_at", table_name="crawler_run")
    op.drop_index("ix_crawler_plan_created_at", table_name="crawler_plan")
