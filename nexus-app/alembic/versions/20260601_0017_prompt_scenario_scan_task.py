"""Prompt scenario and scan-task contract support.

Revision ID: 20260601_0017
Revises: 20260601_0016
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260601_0017"
down_revision: str | None = "20260601_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "ai_prompt_profile" not in tables:
        # Table doesn't exist — nothing to migrate (fresh DB from models)
        return

    op.add_column(
        "ai_prompt_profile",
        sa.Column("scenario", sa.String(length=80), nullable=False, server_default="default"),
    )
    op.alter_column("ai_prompt_profile", "scenario", server_default=None)


def downgrade() -> None:
    op.drop_column("ai_prompt_profile", "scenario")
