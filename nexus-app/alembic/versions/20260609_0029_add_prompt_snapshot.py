"""add prompt_snapshot to ai_governance_run, make profile_id nullable

Revision ID: 20260609_0029
Revises: 20260609_0028
Create Date: 2026-06-09 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_0029"
down_revision: Union[str, None] = "20260609_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "ai_governance_run" not in tables:
        # Table doesn't exist — nothing to migrate (fresh DB from models)
        return

    # ai_governance_run: record which prompt templates were used (multi-stage)
    op.add_column("ai_governance_run",
                  sa.Column("prompt_snapshot", sa.JSON(), nullable=True))
    # Make profile_id nullable since multi-stage uses multiple prompt templates
    op.alter_column("ai_governance_run", "profile_id", nullable=True)


def downgrade() -> None:
    op.alter_column("ai_governance_run", "profile_id", nullable=False)
    op.drop_column("ai_governance_run", "prompt_snapshot")
