"""Add audit event for synchronous data sync run controls.

Revision ID: 20260930_0109
Revises: 20260930_0108
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260930_0109"
down_revision: str | None = "20260930_0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'DataSyncRunControlled'")


def downgrade() -> None:
    pass
