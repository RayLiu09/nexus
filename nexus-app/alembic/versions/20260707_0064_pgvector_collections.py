"""Create pgvector collection and embedding projection tables.

Revision ID: 20260707_0064
Revises: 20260703_0063
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260707_0064"
down_revision: str | None = "20260703_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_default() -> sa.TextClause:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def _json_type() -> sa.types.TypeEngine:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def _embedding_column() -> sa.Column:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return sa.Column("embedding", sa.TEXT(), nullable=False)
    return sa.Column("embedding", sa.JSON(), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "vector_collection",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("collection_key", sa.String(256), nullable=False),
        sa.Column("asset_domain_type", sa.String(80), nullable=False),
        sa.Column("normalized_type", sa.String(40), nullable=False),
        sa.Column("embedding_provider", sa.String(40), nullable=False, server_default="litellm"),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(32), nullable=False, server_default="cosine"),
        sa.Column("metadata_schema_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("metadata", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_key", name="uq_vector_collection_key"),
    )
    op.create_index(
        "ix_vector_collection_lookup",
        "vector_collection",
        ["asset_domain_type", "normalized_type", "embedding_model"],
    )
    op.create_index("ix_vector_collection_status", "vector_collection", ["status"])

    op.create_table(
        "knowledge_embedding_pgvector",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "collection_id",
            sa.String(36),
            sa.ForeignKey("vector_collection.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("collection_key", sa.String(256), nullable=False),
        sa.Column(
            "chunk_id",
            sa.String(36),
            sa.ForeignKey("knowledge_chunk.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id",
            sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column(
            "asset_version_id",
            sa.String(36),
            sa.ForeignKey("asset_version.id"),
            nullable=False,
        ),
        sa.Column("asset_domain_type", sa.String(80), nullable=False),
        sa.Column("knowledge_type_code", sa.String(64), nullable=False),
        sa.Column("domain_profile", sa.String(80), nullable=True),
        sa.Column("normalized_type", sa.String(40), nullable=False),
        sa.Column("content_type", sa.String(40), nullable=True),
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("chunk_type", sa.String(64), nullable=False),
        sa.Column("chunking_strategy", sa.String(64), nullable=False),
        sa.Column("embedding_provider", sa.String(40), nullable=False, server_default="litellm"),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(32), nullable=False, server_default="cosine"),
        sa.Column("metadata_schema_version", sa.String(32), nullable=False, server_default="v1"),
        _embedding_column(),
        sa.Column("embedding_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("collection_id", "chunk_id", name="uq_kep_collection_chunk"),
    )
    if is_postgresql:
        op.execute(
            "ALTER TABLE knowledge_embedding_pgvector "
            "ALTER COLUMN embedding TYPE vector(1024) USING embedding::vector"
        )

    op.create_index(
        "ix_kep_collection_model",
        "knowledge_embedding_pgvector",
        ["collection_id", "embedding_model"],
    )
    op.create_index(
        "ix_kep_collection_domain",
        "knowledge_embedding_pgvector",
        ["collection_id", "asset_domain_type"],
    )
    op.create_index("ix_kep_normalized_ref_id", "knowledge_embedding_pgvector", ["normalized_ref_id"])
    op.create_index("ix_kep_asset_version_id", "knowledge_embedding_pgvector", ["asset_version_id"])
    op.create_index(
        "ix_kep_filter_common",
        "knowledge_embedding_pgvector",
        ["asset_domain_type", "content_type", "language"],
    )
    if is_postgresql:
        op.create_index(
            "ix_kep_metadata_gin",
            "knowledge_embedding_pgvector",
            ["metadata"],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_kep_embedding_hnsw_cosine",
            "knowledge_embedding_pgvector",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    op.drop_table("knowledge_embedding_pgvector")
    op.drop_table("vector_collection")
