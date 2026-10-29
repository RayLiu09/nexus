"""Register the API data sync plan update audit event.

The original data-sync plan migration registered the create/status-control
events but omitted ``DataSyncPlanUpdated`` even though the update service
already emits it.  Keep this corrective migration separate so databases that
already applied the original migration receive the enum value as well.

Revision ID: 20261029_0126
Revises: 20261027_0125
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261029_0126"
down_revision: str | None = "20261027_0125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE auditeventtype "
                "ADD VALUE IF NOT EXISTS 'DataSyncPlanUpdated'"
            )


def downgrade() -> None:
    # PostgreSQL does not support removing an individual enum value safely.
    pass
