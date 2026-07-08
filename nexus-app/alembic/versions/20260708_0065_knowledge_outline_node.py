"""Create knowledge_outline_node table + knowledge_chunk.knowledge_outline_node_id.

Revision ID: 20260708_0065
Revises: 20260707_0064
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260708_0065"
down_revision: str | None = "20260707_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def upgrade() -> None:
    # Extend the PostgreSQL audit-event enum. Idempotent so dev environments
    # can be re-run without manual cleanup; the committed schema stays the
    # single source of truth. No JobType extension: outline construction is
    # synchronous (GET auto-builds on first hit; POST rebuild rebuilds inline).
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'KnowledgeOutlineBuilt'"
    )
    op.execute(
        "ALTER TYPE auditeventtype "
        "ADD VALUE IF NOT EXISTS 'KnowledgeOutlineRebuildRequested'"
    )

    op.create_table(
        "knowledge_outline_node",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id", sa.String(36),
            sa.ForeignKey("knowledge_outline_node.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("numbering", sa.String(64), nullable=True),
        # numbering_path stores lexicographic sort key: e.g. [1,2,3] for "1.2.3".
        # SQLAlchemy JSON generic maps to jsonb on PostgreSQL.
        sa.Column("numbering_path", sa.JSON(), nullable=True),
        # anchor_range: {start, end, page_start, page_end, block_ids: [...]}.
        # Populated on LEAF nodes only; internal nodes may aggregate on read.
        sa.Column("anchor_range", sa.JSON(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        # build_run_id ties every node in a tree to the specific normalize
        # sub-step or rebuild worker invocation that produced it. Enables
        # atomic replace during rebuild.
        sa.Column("build_run_id", sa.String(36), nullable=False),
        sa.Column(
            "fallback_used", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
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
            "normalized_ref_id", "parent_id", "order_index",
            name="uq_knowledge_outline_sibling_order",
        ),
        sa.CheckConstraint(
            "level >= 0 AND level <= 3",
            name="ck_knowledge_outline_level_range",
        ),
    )
    op.create_index(
        "ix_knowledge_outline_node_ref_level",
        "knowledge_outline_node",
        ["normalized_ref_id", "level"],
    )
    op.create_index(
        "ix_knowledge_outline_node_parent_id",
        "knowledge_outline_node",
        ["parent_id"],
    )
    op.create_index(
        "ix_knowledge_outline_node_build_run_id",
        "knowledge_outline_node",
        ["build_run_id"],
    )

    # Chunk-to-leaf backfill. Dedicated column avoids namespace collision with
    # task_outline's chunk_metadata.outline_node_id key.
    op.add_column(
        "knowledge_chunk",
        sa.Column(
            "knowledge_outline_node_id", sa.String(36),
            sa.ForeignKey("knowledge_outline_node.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_knowledge_chunk_outline_node_id",
        "knowledge_chunk",
        ["knowledge_outline_node_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_chunk_outline_node_id",
        table_name="knowledge_chunk",
    )
    op.drop_column("knowledge_chunk", "knowledge_outline_node_id")

    op.drop_index(
        "ix_knowledge_outline_node_build_run_id",
        table_name="knowledge_outline_node",
    )
    op.drop_index(
        "ix_knowledge_outline_node_parent_id",
        table_name="knowledge_outline_node",
    )
    op.drop_index(
        "ix_knowledge_outline_node_ref_level",
        table_name="knowledge_outline_node",
    )
    op.drop_table("knowledge_outline_node")
    # PostgreSQL cannot cleanly ALTER TYPE DROP VALUE for enums; leaving
    # 'KnowledgeOutlineBuilt' / 'KnowledgeOutlineRebuildRequested' in the
    # auditeventtype enum is safe as they become unreferenced values on
    # downgrade.
