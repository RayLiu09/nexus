"""Sync indexmanifeststatus enum for stale manifests.

Revision ID: 20260703_0063
Revises: 20260703_0062
Create Date: 2026-07-03
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import IndexManifestStatus

revision: str = "20260703_0063"
down_revision: str | None = "20260703_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in IndexManifestStatus:
        op.execute(
            f"ALTER TYPE indexmanifeststatus ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL cannot drop enum values in-place. The value is additive and
    # backward compatible; downgrades keep the enum member.
    pass
