"""Add refresh-token rotation idempotency pointer.

Revision ID: 20260616_0033
Revises: 20260615_0032
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260616_0033"
down_revision: str | None = "20260615_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_token", sa.Column("rotated_to_jti", sa.String(64), nullable=True))
    op.create_index("ix_refresh_token_rotated_to_jti", "refresh_token", ["rotated_to_jti"])


def downgrade() -> None:
    op.drop_index("ix_refresh_token_rotated_to_jti", table_name="refresh_token")
    op.drop_column("refresh_token", "rotated_to_jti")
