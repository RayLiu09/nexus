"""Add document_metadata JSON column to normalized_asset_ref.

Per docs/rag_semantic_chunks_implementation_plan.md §五 slice 0+1, this
column carries document-level metadata (title, authors, publish_date,
keywords, abstract, outline) extracted from the first cluster of blocks
during normalize. Stored here (NOT in chunk_metadata) so a million
chunks pointing at the same document don't each carry redundant copies
of the title / authors / abstract.

Nullable so existing rows are unaffected; backfill is handled by the
next normalize pass per asset.

Revision ID: 20260622_0036
Revises: 20260622_0035
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0036"
down_revision: str | None = "20260622_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "normalized_asset_ref",
        sa.Column(
            "document_metadata",
            sa.JSON(),
            nullable=True,
            comment=(
                "Document-level metadata extracted from blocks (title, authors, "
                "publish_date, keywords, abstract, outline, source_block_ids). "
                "Used as every chunk's parent context and asset-detail rendering; "
                "NEVER duplicated into per-chunk metadata."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("normalized_asset_ref", "document_metadata")
