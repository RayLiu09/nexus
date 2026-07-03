"""Create Task Outline profile and node tables.

Revision ID: 20260703_0062
Revises: 20260701_0061
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260703_0062"
down_revision: str | None = "20260701_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def _json_array_default() -> sa.TextClause:
    return sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "task_outline_profile",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column(
            "asset_version_id", sa.String(36),
            sa.ForeignKey("asset_version.id"),
            nullable=False,
        ),
        sa.Column("asset_profile", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("textbook_subtype", sa.String(64), nullable=True),
        sa.Column("task_profile", sa.String(64), nullable=True),
        sa.Column("subtype_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("processing_profile", sa.String(64), nullable=False),
        sa.Column("evidence_graph_admission", sa.String(64), nullable=False),
        sa.Column(
            "source_block_ids", sa.JSON(), nullable=False,
            server_default=_json_array_default(),
        ),
        sa.Column("quality", sa.JSON(), nullable=False, server_default=_json_default()),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=_json_default()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "normalized_ref_id", "asset_profile",
            name="uq_task_outline_profile_ref_asset_profile",
        ),
    )
    op.create_index(
        "ix_task_outline_profile_normalized_ref_id",
        "task_outline_profile",
        ["normalized_ref_id"],
    )
    op.create_index(
        "ix_task_outline_profile_asset_version_id",
        "task_outline_profile",
        ["asset_version_id"],
    )
    op.create_index(
        "ix_task_outline_profile_processing",
        "task_outline_profile",
        ["processing_profile"],
    )

    op.create_table(
        "task_outline_node",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("task_outline_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id", sa.String(36),
            sa.ForeignKey("task_outline_node.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("section_type", sa.String(64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("order_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "source_block_ids", sa.JSON(), nullable=False,
            server_default=_json_array_default(),
        ),
        sa.Column("locator", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=_json_default()),
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
        "ix_task_outline_node_normalized_ref_id",
        "task_outline_node",
        ["normalized_ref_id"],
    )
    op.create_index(
        "ix_task_outline_node_profile_id",
        "task_outline_node",
        ["profile_id"],
    )
    op.create_index(
        "ix_task_outline_node_parent_id",
        "task_outline_node",
        ["parent_id"],
    )
    op.create_index(
        "ix_task_outline_node_profile_order",
        "task_outline_node",
        ["profile_id", "order_no"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_outline_node_profile_order", table_name="task_outline_node")
    op.drop_index("ix_task_outline_node_parent_id", table_name="task_outline_node")
    op.drop_index("ix_task_outline_node_profile_id", table_name="task_outline_node")
    op.drop_index("ix_task_outline_node_normalized_ref_id", table_name="task_outline_node")
    op.drop_table("task_outline_node")

    op.drop_index("ix_task_outline_profile_processing", table_name="task_outline_profile")
    op.drop_index(
        "ix_task_outline_profile_asset_version_id",
        table_name="task_outline_profile",
    )
    op.drop_index(
        "ix_task_outline_profile_normalized_ref_id",
        table_name="task_outline_profile",
    )
    op.drop_table("task_outline_profile")

