"""B8.1 — CapabilityGraphStaging tables (build / node / edge).

Three-table staging layer between Pipeline B domain reads (job_demand_*,
occupational_*) and a future formal capability graph. Schema source:
`docs/pipeline_b_contract_freeze.md §5.12` + design `§七`.

Cascade chain:
- Deleting a normalized_asset_ref drops every build hung off it (build
  is the entry point — losing the ref means the build is unreferenceable).
- Deleting a build cascades to its nodes + edges (per §5.12 "构图批次"
  semantics).
- Deleting a node cascades to its incident edges so we don't end up with
  edges pointing at vanished nodes.

The edge_type / node_type whitelists are enforced at the application
layer (`capability_graph/whitelists.py`) rather than DB CHECKs — design
§7.4 explicitly leaves the lists growable post-P0.

Revision ID: 20260628_0052
Revises: 20260628_0051
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260628_0052"
down_revision: str | None = "20260628_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capability_graph_staging_build",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("build_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column(
            "quality_summary", sa.JSON(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_cgsb_normalized_ref_id",
        "capability_graph_staging_build", ["normalized_ref_id"],
    )
    op.create_index(
        "ix_cgsb_status", "capability_graph_staging_build", ["status"],
    )

    op.create_table(
        "capability_graph_staging_node",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_id", sa.String(36),
            sa.ForeignKey(
                "capability_graph_staging_build.id", ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("node_key", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("canonical_name", sa.String(512), nullable=True),
        sa.Column("source_table", sa.String(64), nullable=True),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column(
            "properties", sa.JSON(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("build_id", "node_type", "node_key", name="uq_cgsn"),
    )
    op.create_index(
        "ix_cgsn_build_id", "capability_graph_staging_node", ["build_id"],
    )
    op.create_index(
        "ix_cgsn_type", "capability_graph_staging_node", ["node_type"],
    )

    op.create_table(
        "capability_graph_staging_edge",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_id", sa.String(36),
            sa.ForeignKey(
                "capability_graph_staging_build.id", ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "source_node_id", sa.String(36),
            sa.ForeignKey(
                "capability_graph_staging_node.id", ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "target_node_id", sa.String(36),
            sa.ForeignKey(
                "capability_graph_staging_node.id", ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("edge_type", sa.String(64), nullable=False),
        sa.Column("source_table", sa.String(64), nullable=True),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column(
            "evidence", sa.JSON(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "build_id", "source_node_id", "target_node_id", "edge_type",
            name="uq_cgse",
        ),
    )
    op.create_index(
        "ix_cgse_build_id", "capability_graph_staging_edge", ["build_id"],
    )
    op.create_index(
        "ix_cgse_edge_type", "capability_graph_staging_edge", ["edge_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_cgse_edge_type", table_name="capability_graph_staging_edge")
    op.drop_index("ix_cgse_build_id", table_name="capability_graph_staging_edge")
    op.drop_table("capability_graph_staging_edge")
    op.drop_index("ix_cgsn_type", table_name="capability_graph_staging_node")
    op.drop_index("ix_cgsn_build_id", table_name="capability_graph_staging_node")
    op.drop_table("capability_graph_staging_node")
    op.drop_index("ix_cgsb_status", table_name="capability_graph_staging_build")
    op.drop_index(
        "ix_cgsb_normalized_ref_id",
        table_name="capability_graph_staging_build",
    )
    op.drop_table("capability_graph_staging_build")
