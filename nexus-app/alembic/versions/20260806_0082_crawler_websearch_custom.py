"""Add WebSearch Custom crawler plan fields.

Revision ID: 20260806_0082
Revises: 20260804_0081
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision = "20260806_0082"
down_revision = "20260804_0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("crawler_plan", sa.Column("connector_type", sa.String(32), nullable=False, server_default="firecrawl"))
    op.add_column("crawler_plan", sa.Column("connector_version", sa.String(32), nullable=False, server_default="v2"))
    op.add_column("crawler_plan", sa.Column("search_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("crawler_run", sa.Column("connector_type", sa.String(32), nullable=False, server_default="firecrawl"))
    op.add_column("crawler_run", sa.Column("connector_version", sa.String(32), nullable=False, server_default="v2"))

def downgrade() -> None:
    op.drop_column("crawler_run", "connector_version")
    op.drop_column("crawler_run", "connector_type")
    op.drop_column("crawler_plan", "search_policy")
    op.drop_column("crawler_plan", "connector_version")
    op.drop_column("crawler_plan", "connector_type")
