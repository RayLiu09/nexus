"""Sync chunktype + chunkingstrategy enums — pick up SEMANTIC_BLOCK / SEMANTIC_REPACK.

Background:
- Slice 2 of docs/rag_semantic_chunks_implementation_plan.md introduces a
  semantic-repack layer that converts normalized blocks into N retrieval-
  grade ``SEMANTIC_BLOCK`` chunks. The previous design emitted ONE
  ``PASSTHROUGH_DESCRIPTOR`` chunk per emission and deferred chunking to
  RAGFlow — the new design has Nexus own segmentation so each chunk
  carries an exact ``locator`` (md_char_range / md_spans / page span /
  bbox / heading_path / anchor_role).
- Pattern follows 0035 (auditeventtype sync): idempotent
  ``ALTER TYPE ... ADD VALUE IF NOT EXISTS`` for every member of the two
  enums. Safe to re-run.

Revision ID: 20260622_0037
Revises: 20260622_0036
Create Date: 2026-06-22
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import ChunkingStrategy, ChunkType

revision: str = "20260622_0037"
down_revision: str | None = "20260622_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in ChunkType:
        op.execute(
            f"ALTER TYPE chunktype ADD VALUE IF NOT EXISTS '{member.value}'"
        )
    for member in ChunkingStrategy:
        op.execute(
            f"ALTER TYPE chunkingstrategy ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL has no safe in-place DROP VALUE for enums.
    pass
