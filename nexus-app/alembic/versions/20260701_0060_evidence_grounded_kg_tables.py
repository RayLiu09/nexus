"""Create Evidence-grounded Knowledge Graph tables.

Revision ID: 20260701_0060
Revises: 20260701_0059
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_0060"
down_revision: str | None = "20260701_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def _json_array_default() -> sa.TextClause:
    return sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "knowledge_graph_build",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "graph_type", sa.String(64), nullable=False,
            server_default="evidence_grounded_kg",
        ),
        sa.Column("graph_profile", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_summary", sa.JSON(), nullable=False, server_default=_json_default()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_kgb_ref_profile_strategy",
        "knowledge_graph_build",
        ["normalized_ref_id", "graph_profile", "strategy_version"],
    )
    op.create_index(
        "ix_kgb_status_created",
        "knowledge_graph_build",
        ["status", "created_at"],
    )

    op.create_table(
        "knowledge_graph_node",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "graph_build_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_key", sa.String(512), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column("properties", sa.JSON(), nullable=False, server_default=_json_default()),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("graph_build_id", "node_key", name="uq_kgn_build_key"),
    )
    op.create_index(
        "ix_kgn_build_type",
        "knowledge_graph_node",
        ["graph_build_id", "node_type"],
    )
    op.create_index(
        "ix_kgn_normalized_ref_id",
        "knowledge_graph_node",
        ["normalized_ref_id"],
    )

    op.create_table(
        "knowledge_graph_fact",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "graph_build_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact_type", sa.String(64), nullable=False),
        sa.Column(
            "subject_node_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("predicate", sa.String(128), nullable=False),
        sa.Column(
            "object_node_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_node.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("object_literal", sa.Text(), nullable=True),
        sa.Column("qualifiers", sa.JSON(), nullable=False, server_default=_json_default()),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_kgf_build_type",
        "knowledge_graph_fact",
        ["graph_build_id", "fact_type"],
    )
    op.create_index("ix_kgf_subject", "knowledge_graph_fact", ["subject_node_id"])
    op.create_index("ix_kgf_object_node", "knowledge_graph_fact", ["object_node_id"])
    op.create_index(
        "ix_kgf_normalized_ref_id",
        "knowledge_graph_fact",
        ["normalized_ref_id"],
    )

    op.create_table(
        "knowledge_graph_edge",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "graph_build_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_node_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(128), nullable=False),
        sa.Column(
            "target_node_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("properties", sa.JSON(), nullable=False, server_default=_json_default()),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_kge_build_type",
        "knowledge_graph_edge",
        ["graph_build_id", "relation_type"],
    )
    op.create_index(
        "ix_kge_nodes",
        "knowledge_graph_edge",
        ["source_node_id", "target_node_id"],
    )
    op.create_index(
        "ix_kge_normalized_ref_id",
        "knowledge_graph_edge",
        ["normalized_ref_id"],
    )

    op.create_table(
        "knowledge_graph_mention",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "graph_build_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id", sa.String(36),
            sa.ForeignKey("knowledge_chunk.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(512), nullable=True),
        sa.Column("source_block_ids", sa.JSON(), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_kgm_build_entity",
        "knowledge_graph_mention",
        ["graph_build_id", "entity_id"],
    )
    op.create_index("ix_kgm_chunk_id", "knowledge_graph_mention", ["chunk_id"])
    op.create_index(
        "ix_kgm_normalized_ref_id",
        "knowledge_graph_mention",
        ["normalized_ref_id"],
    )

    op.create_table(
        "knowledge_graph_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "graph_build_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fact_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_fact.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "edge_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_edge.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "entity_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "mention_id", sa.String(36),
            sa.ForeignKey("knowledge_graph_mention.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "chunk_id", sa.String(36),
            sa.ForeignKey("knowledge_chunk.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_block_ids", sa.JSON(), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_kgev_chunk_id", "knowledge_graph_evidence", ["chunk_id"])
    op.create_index(
        "ix_kgev_fact", "knowledge_graph_evidence", ["graph_build_id", "fact_id"],
    )
    op.create_index(
        "ix_kgev_edge", "knowledge_graph_evidence", ["graph_build_id", "edge_id"],
    )
    op.create_index(
        "ix_kgev_entity", "knowledge_graph_evidence",
        ["graph_build_id", "entity_id"],
    )
    op.create_index(
        "ix_kgev_mention", "knowledge_graph_evidence",
        ["graph_build_id", "mention_id"],
    )
    op.create_index(
        "ix_kgev_normalized_ref_id",
        "knowledge_graph_evidence",
        ["normalized_ref_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_kgev_normalized_ref_id", table_name="knowledge_graph_evidence")
    op.drop_index("ix_kgev_mention", table_name="knowledge_graph_evidence")
    op.drop_index("ix_kgev_entity", table_name="knowledge_graph_evidence")
    op.drop_index("ix_kgev_edge", table_name="knowledge_graph_evidence")
    op.drop_index("ix_kgev_fact", table_name="knowledge_graph_evidence")
    op.drop_index("ix_kgev_chunk_id", table_name="knowledge_graph_evidence")
    op.drop_table("knowledge_graph_evidence")

    op.drop_index("ix_kgm_normalized_ref_id", table_name="knowledge_graph_mention")
    op.drop_index("ix_kgm_chunk_id", table_name="knowledge_graph_mention")
    op.drop_index("ix_kgm_build_entity", table_name="knowledge_graph_mention")
    op.drop_table("knowledge_graph_mention")

    op.drop_index("ix_kge_normalized_ref_id", table_name="knowledge_graph_edge")
    op.drop_index("ix_kge_nodes", table_name="knowledge_graph_edge")
    op.drop_index("ix_kge_build_type", table_name="knowledge_graph_edge")
    op.drop_table("knowledge_graph_edge")

    op.drop_index("ix_kgf_normalized_ref_id", table_name="knowledge_graph_fact")
    op.drop_index("ix_kgf_object_node", table_name="knowledge_graph_fact")
    op.drop_index("ix_kgf_subject", table_name="knowledge_graph_fact")
    op.drop_index("ix_kgf_build_type", table_name="knowledge_graph_fact")
    op.drop_table("knowledge_graph_fact")

    op.drop_index("ix_kgn_normalized_ref_id", table_name="knowledge_graph_node")
    op.drop_index("ix_kgn_build_type", table_name="knowledge_graph_node")
    op.drop_table("knowledge_graph_node")

    op.drop_index("ix_kgb_status_created", table_name="knowledge_graph_build")
    op.drop_index("ix_kgb_ref_profile_strategy", table_name="knowledge_graph_build")
    op.drop_table("knowledge_graph_build")
