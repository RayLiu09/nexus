"""Add audit events for teaching-standard business view mutations.

Revision ID: 20260907_0100
Revises: 20260907_0099
"""
from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260907_0100"
down_revision: str | None = "20260907_0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in (
        AuditEventType.TEACHING_STANDARD_COURSE_UPDATED,
        AuditEventType.TEACHING_STANDARD_LIBRARY_ACTIVATED,
    ):
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place.
    pass
