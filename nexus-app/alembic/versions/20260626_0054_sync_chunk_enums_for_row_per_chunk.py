"""Sync chunktype + chunkingstrategy enums — pick up STRUCTURED_RECORD_ROW / ROW_DECOMPOSE.

Background:
- Pipeline B record-pipeline KTs (e.g. ``structured_record_table`` for
  job_demand) declare ``chunking_mode=row_per_chunk`` +
  ``chunking_strategy=row_decompose`` in ``governance_rules_v2.json``.
  Wiring up the corresponding chunking path requires two new enum members
  for ``KnowledgeChunk.chunk_type`` (``structured_record_row``) and
  ``KnowledgeChunk.chunking_strategy`` (``row_decompose``).
- Pattern matches 0037: idempotent ``ALTER TYPE ... ADD VALUE IF NOT
  EXISTS`` for every member of both Python enums. Safe to re-run.

Revision ID: 20260626_0054
Revises: 20260628_0053
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import ChunkingStrategy, ChunkType

revision: str = "20260626_0054"
down_revision: str | None = "20260628_0053"
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
