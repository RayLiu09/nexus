"""Create knowledge_outline_review_item table + review-status enums.

Revision ID: 20260709_0067
Revises: 20260708_0066
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260709_0067"
down_revision: str | None = "20260708_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def upgrade() -> None:
    # Audit-event enum additions for the review lifecycle.
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'KnowledgeOutlineReviewItemCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'KnowledgeOutlineReviewItemOverridden'"
    )
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'KnowledgeOutlineReviewItemApproved'"
    )

    op.create_table(
        "knowledge_outline_review_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ai_run_id", sa.String(36),
            sa.ForeignKey("ai_governance_run.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # heading_block_id is the stable anchor across rebuilds — SME
        # override travels with the block, not with a specific run.
        sa.Column("heading_block_id", sa.String(64), nullable=False),
        sa.Column("heading_text", sa.Text(), nullable=False),
        sa.Column("llm_label", sa.String(32), nullable=False),
        sa.Column("llm_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("llm_reason", sa.String(120), nullable=True),
        sa.Column("confidence_bucket", sa.String(8), nullable=False),
        sa.Column("sme_override_label", sa.String(32), nullable=True),
        sa.Column("sme_override_reason", sa.String(300), nullable=True),
        sa.Column("sme_override_by", sa.String(36), nullable=True),
        sa.Column(
            "sme_override_at", sa.DateTime(timezone=True), nullable=True,
        ),
        # pending | approved | overridden | dismissed
        sa.Column(
            "status", sa.String(16), nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "metadata", sa.JSON(),
            nullable=False, server_default=_json_default(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "normalized_ref_id", "heading_block_id",
            name="uq_knowledge_outline_review_ref_block",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'overridden', 'dismissed')",
            name="ck_knowledge_outline_review_status",
        ),
        sa.CheckConstraint(
            "confidence_bucket IN ('high', 'mid', 'low')",
            name="ck_knowledge_outline_review_bucket",
        ),
    )
    op.create_index(
        "ix_knowledge_outline_review_ref_status",
        "knowledge_outline_review_item",
        ["normalized_ref_id", "status"],
    )
    op.create_index(
        "ix_knowledge_outline_review_ai_run_id",
        "knowledge_outline_review_item",
        ["ai_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_outline_review_ai_run_id",
        table_name="knowledge_outline_review_item",
    )
    op.drop_index(
        "ix_knowledge_outline_review_ref_status",
        table_name="knowledge_outline_review_item",
    )
    op.drop_table("knowledge_outline_review_item")
    # PostgreSQL enum values are not dropped on downgrade — leaving
    # 'KnowledgeOutlineReviewItemCreated' etc. in auditeventtype is safe.
