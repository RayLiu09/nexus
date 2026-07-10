"""Create tag_asset_index — v1.3 §2 semantic inverted枢纽.

The table is the single write target for every projection hook (Pipeline
B writers, outline generator, governance tag投影 job, Console manual
authoring) and the single read source for ``TagAssetIndexResolver``.
See ``docs/knowledge_retrieval_result_enhancement_v1.3.md §2`` and
``docs/tag_filter_reliability_matrix_v1.md`` for the full contract.

Column contract mirrors ``nexus_app.models.TagAssetIndex``.  Highlights:

* ``tag_type`` is a free-text column bound to
  ``tag_taxonomy.TAG_TAXONOMY_V1_3`` at the Pydantic layer, not by a DB
  enum — extending the taxonomy must not require an ``ALTER TYPE``.
* ``tag_value_normalized`` is populated by the projection hook via
  ``nexus_app.ai_governance.tag_normalization.normalize_tag_value``;
  L1/L1.5/L2 all read this column.
* ``standard_code`` is nullable; the ``ix_tai_type_code`` index is
  a partial index so L3 lookups don't scan NULL rows.
* ``tag_embedding`` is nullable — the async embedding worker fills it
  in; rows without an embedding get bypassed at L4 (matrix I-6).
* ``target_type`` and ``source`` are DB enums so we can rely on shape
  guarantees at read time (and can enumerate them from the Enum reflect
  table for admin panels).

HNSW index on ``tag_embedding`` is PostgreSQL-only (pgvector cosine ops).
SQLite tests skip the index creation but still exercise all other CRUD.

Revision ID: 20260710_0070
Revises: 20260710_0069
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0070"
down_revision: str | None = "20260710_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TAG_ASSET_INDEX_TARGET_TYPE_VALUES = (
    "normalized_asset_ref",
    "outline_node",
    "job_demand_record",
    "job_demand_requirement_item",
    "major_distribution_record",
    "occupational_ability_item",
)

_TAG_ASSET_INDEX_SOURCE_VALUES = (
    "field_projection",
    "outline_projection",
    "governance_tag",
    "expert_manual",
    "dict_alias_hit",
)


def _embedding_column(is_postgresql: bool) -> sa.Column:
    """pgvector on PostgreSQL; JSON fallback for SQLite so ORM tests stay
    dialect-portable."""
    if is_postgresql:
        # We create the column as TEXT here and ALTER it to vector(512)
        # below — sqlalchemy's core doesn't know the pgvector type, and
        # doing the ALTER lets us keep this migration free of a pgvector
        # python dep.  Same pattern as the 0064 knowledge embeddings.
        return sa.Column("tag_embedding", sa.TEXT(), nullable=True)
    return sa.Column("tag_embedding", sa.JSON(), nullable=True)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        # Extension is likely already present (0064), but the CREATE IF
        # NOT EXISTS keeps the migration idempotent when applied against
        # a fresh cluster.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    target_type_enum = sa.Enum(
        *_TAG_ASSET_INDEX_TARGET_TYPE_VALUES,
        name="tagassetindextargettype",
    )
    source_enum = sa.Enum(
        *_TAG_ASSET_INDEX_SOURCE_VALUES,
        name="tagassetindexsource",
    )

    op.create_table(
        "tag_asset_index",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tag_type",
            sa.String(32),
            nullable=False,
            comment="One of tag_taxonomy.types[*].code",
        ),
        sa.Column("tag_value", sa.Text(), nullable=False),
        sa.Column("tag_value_normalized", sa.Text(), nullable=False),
        sa.Column("standard_code", sa.Text(), nullable=True),
        _embedding_column(is_postgresql),
        sa.Column("target_type", target_type_enum, nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extraction_run_id", sa.String(36), nullable=True),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    if is_postgresql:
        op.execute(
            "ALTER TABLE tag_asset_index "
            "ALTER COLUMN tag_embedding TYPE vector(512) "
            "USING tag_embedding::vector"
        )

    # L1 / L1.5 / L2 exact + normalised value lookup
    op.create_index(
        "ix_tai_type_norm",
        "tag_asset_index",
        ["tag_type", "tag_value_normalized"],
    )

    # L3 dictionary standard code — partial index skips NULL rows
    if is_postgresql:
        op.create_index(
            "ix_tai_type_code",
            "tag_asset_index",
            ["tag_type", "standard_code"],
            postgresql_where=sa.text("standard_code IS NOT NULL"),
        )
    else:
        # SQLite doesn't honour postgresql_where but still needs a
        # regular composite so ORM __table_args__ round-trips cleanly.
        op.create_index(
            "ix_tai_type_code",
            "tag_asset_index",
            ["tag_type", "standard_code"],
        )

    # Reverse lookup — "which tags does this target carry"
    op.create_index(
        "ix_tai_target",
        "tag_asset_index",
        ["target_type", "target_id"],
    )

    # Cache invalidation — flush all rows for a version in one sweep
    op.create_index(
        "ix_tai_asset_version",
        "tag_asset_index",
        ["asset_version_id"],
    )

    # Source projection auditability
    op.create_index(
        "ix_tai_source",
        "tag_asset_index",
        ["source"],
    )

    if is_postgresql:
        op.create_index(
            "ix_tai_embedding_hnsw_cosine",
            "tag_asset_index",
            ["tag_embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"tag_embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        op.drop_index("ix_tai_embedding_hnsw_cosine", "tag_asset_index")
    op.drop_index("ix_tai_source", "tag_asset_index")
    op.drop_index("ix_tai_asset_version", "tag_asset_index")
    op.drop_index("ix_tai_target", "tag_asset_index")
    op.drop_index("ix_tai_type_code", "tag_asset_index")
    op.drop_index("ix_tai_type_norm", "tag_asset_index")
    op.drop_table("tag_asset_index")

    if is_postgresql:
        op.execute("DROP TYPE IF EXISTS tagassetindexsource")
        op.execute("DROP TYPE IF EXISTS tagassetindextargettype")
