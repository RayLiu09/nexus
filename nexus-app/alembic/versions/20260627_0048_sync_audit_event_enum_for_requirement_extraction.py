"""Sync auditeventtype enum — pick up Pipeline B B5.2 extraction event.

Adds `REQUIREMENT_ITEMS_EXTRACTED` to the postgres enum. Same idempotent
pattern as earlier syncs (0031 / 0034 / 0035 / 0038 / 0039 / 0040 / 0042 /
0045): re-issue `ALTER TYPE ... ADD VALUE IF NOT EXISTS` for every member,
so the migration is safe to re-run and so any earlier additions that
didn't land are picked up at the same time.

Revision ID: 20260627_0048
Revises: 20260627_0047
Create Date: 2026-06-27
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260627_0048"
down_revision: str | None = "20260627_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL has no safe in-place DROP VALUE for enums.
    pass
