"""Add cleaned titles and collection regions to raw jobs.

Revision ID: 20261117_0132
Revises: 20261116_0131
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261117_0132"
down_revision: str | None = "20261116_0131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raw_jobs", sa.Column("title_normalized", sa.Text(), nullable=True))
    op.add_column("raw_jobs", sa.Column("region", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_jobs", "region")
    op.drop_column("raw_jobs", "title_normalized")
