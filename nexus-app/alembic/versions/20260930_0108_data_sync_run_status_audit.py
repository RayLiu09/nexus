"""Add audit event for data sync run state transitions.

Revision ID: 20260930_0108
Revises: 20260930_0107
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260930_0108"
down_revision: str | None = "20260930_0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'DataSyncRunStatusChanged'")


def downgrade() -> None:
    pass
