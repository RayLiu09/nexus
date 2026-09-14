"""Sync console user CRUD audit event values into ``auditeventtype``.

Revision ID: 20260914_0105
Revises: 20260914_0104
Create Date: 2026-09-14

The user-management audit events were added to the application enum after
the preceding user-account migration had already been applied in some
environments.  Keep this as a new revision so those environments receive the
DDL when operators run ``alembic upgrade head``.
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType


revision: str = "20260914_0105"
down_revision: str | None = "20260914_0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (used by the unit tests) stores enum values as text.
        return

    for member in (
        AuditEventType.USER_CREATED,
        AuditEventType.USER_UPDATED,
        AuditEventType.USER_STATUS_CHANGED,
        AuditEventType.USER_PASSWORD_RESET,
    ):
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL does not support safely removing enum values in place.
    pass
