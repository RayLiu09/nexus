"""Asset-naming cleanup: column + constraint/index renames.

Revision ID: 20260607_0023
Revises: 20260607_0022
Create Date: 2026-06-07

Finishes the asset/asset_version rename started in 0020:

- `parse_artifact.document_version_id` → `parse_artifact.asset_version_id`
  (the FK column kept the legacy prefix while the target table was renamed).
- Internal constraint/index names that still carried `document_` prefixes
  are rebased onto the current table names so DBA tooling and pg_stat output
  match the contract surface.

Functional behavior is unchanged — these are pure rename ops.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260607_0023"
down_revision: str | None = "20260607_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── parse_artifact column rename ───────────────────────────────────────
    op.alter_column(
        "parse_artifact",
        "document_version_id",
        new_column_name="asset_version_id",
    )

    # ── asset / asset_version constraints + indexes ───────────────────────
    op.execute(
        "ALTER TABLE asset RENAME CONSTRAINT uq_document_asset_source_key "
        "TO uq_asset_source_key"
    )
    op.execute(
        "ALTER TABLE asset_version RENAME CONSTRAINT uq_document_version_asset_no "
        "TO uq_asset_version_asset_no"
    )
    op.execute(
        "ALTER INDEX ix_document_version_asset_status "
        "RENAME TO ix_asset_version_asset_status"
    )
    op.execute(
        "ALTER INDEX uq_document_version_one_available_per_asset "
        "RENAME TO uq_asset_version_one_available_per_asset"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX uq_asset_version_one_available_per_asset "
        "RENAME TO uq_document_version_one_available_per_asset"
    )
    op.execute(
        "ALTER INDEX ix_asset_version_asset_status "
        "RENAME TO ix_document_version_asset_status"
    )
    op.execute(
        "ALTER TABLE asset_version RENAME CONSTRAINT uq_asset_version_asset_no "
        "TO uq_document_version_asset_no"
    )
    op.execute(
        "ALTER TABLE asset RENAME CONSTRAINT uq_asset_source_key "
        "TO uq_document_asset_source_key"
    )
    op.alter_column(
        "parse_artifact",
        "asset_version_id",
        new_column_name="document_version_id",
    )
