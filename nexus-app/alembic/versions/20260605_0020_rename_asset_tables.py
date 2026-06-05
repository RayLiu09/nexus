"""Rename `document_asset` → `asset`, `document_version` → `asset_version`.

Revision ID: 20260605_0020
Revises: 20260605_0019
Create Date: 2026-06-05

CLAUDE.md / ARCHITECT.md list these as `asset` and `asset_version` and have
flagged the rename as pending since v3.0. The legacy `document_*` prefix
predates the spec split between "asset master data" (the row) and
"asset_version" (the immutable artifact lineage). External documentation,
data dictionaries, and downstream consumers all already say `asset` /
`asset_version`; this migration aligns the persistence layer with the
contract.

Scope:
- Table renames only. Column names, foreign-key column names, and internal
  constraint/index names (e.g. `uq_document_asset_source_key`) stay as they
  were — they're internal and renaming them on a live cluster needs its own
  coordination window.
- ORM class names `DocumentAsset` / `DocumentVersion` are untouched in this
  PR; they're a Python identifier-level rename that would cascade into
  console TypeScript types, mocks, and API client code.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260605_0020"
down_revision: str | None = "20260605_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("document_asset", "asset")
    op.rename_table("document_version", "asset_version")


def downgrade() -> None:
    op.rename_table("asset_version", "document_version")
    op.rename_table("asset", "document_asset")
