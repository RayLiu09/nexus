"""Add tag_asset_index.evidence_span — v1.3 PR-8 governance projection.

Governance-side projection (source=governance_tag) carries the LLM
``evidence_span`` (per-tag 3-60 char snippet, copy-pasted from the source
document — see docs/knowledge_retrieval_result_enhancement_v1.3.md §16
and default_prompts._TAGGING_PROMPT_V2).  Field/outline projections
leave it NULL because they derive from structured columns rather than
free-text evidence.

Column stays nullable so pre-PR-8 rows validate unchanged and any
future projection sources that don't carry evidence stay legal.

Revision ID: 20260711_0071
Revises: 20260710_0070
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0071"
down_revision: str | None = "20260710_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tag_asset_index",
        sa.Column("evidence_span", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tag_asset_index", "evidence_span")
