"""Add audit event for business-expert report identity edits.

Revision ID: 20261016_0118
Revises: 20261014_0117
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261016_0118"
down_revision: str | None = "20261014_0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
        "'TalentDemandReportIdentityUpdated'"
    )


def downgrade() -> None:
    # Existing audit rows must remain readable.
    pass
