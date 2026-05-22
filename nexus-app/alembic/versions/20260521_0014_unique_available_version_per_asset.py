"""Partial unique index: at most one available version per asset (Review 1.3).

Revision ID: 20260521_0014
Revises: 20260521_0013
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260521_0014"
down_revision: str | None = "20260521_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_document_version_one_available_per_asset",
        "document_version",
        ["asset_id"],
        unique=True,
        postgresql_where=text("version_status = 'available'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_document_version_one_available_per_asset",
        table_name="document_version",
    )
