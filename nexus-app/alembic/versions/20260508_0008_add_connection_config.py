"""add connection_config to data_source

Changes:
- data_source: add connection_config JSONB nullable column

Revision ID: 20260508_0008
Revises: 20260507_0007
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260508_0008"
down_revision: str | None = "20260507_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        op.add_column(
            "data_source",
            sa.Column("connection_config", postgresql.JSONB, nullable=True),
        )
    else:
        with op.batch_alter_table("data_source") as batch_op:
            batch_op.add_column(
                sa.Column("connection_config", sa.JSON, nullable=True)
            )


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        op.drop_column("data_source", "connection_config")
    else:
        with op.batch_alter_table("data_source") as batch_op:
            batch_op.drop_column("connection_config")
