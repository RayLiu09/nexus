"""knowledge_chunk add source_block_ids + locator

Revision ID: 20260610_0030
Revises: 20260609_0029
Create Date: 2026-06-10 09:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260610_0030"
down_revision: Union[str, None] = "20260609_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "knowledge_chunk" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("knowledge_chunk")}

    if "source_block_ids" not in existing:
        op.add_column(
            "knowledge_chunk",
            sa.Column("source_block_ids", sa.JSON(), nullable=True),
        )
    if "locator" not in existing:
        op.add_column(
            "knowledge_chunk",
            sa.Column("locator", sa.JSON(), nullable=True),
        )

    # Backfill: lift legacy chunk_metadata.source_locator into the new locator column.
    # Old shape: {"page": int, "bbox": [...]}
    # New shape: {"page_start","page_end","bbox_union","blocks":[{block_id,page,bbox}]}
    dialect = conn.dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE knowledge_chunk
               SET locator = jsonb_build_object(
                     'page_start', (metadata->'source_locator'->>'page')::int,
                     'page_end',   (metadata->'source_locator'->>'page')::int,
                     'bbox_union', metadata->'source_locator'->'bbox',
                     'blocks',     jsonb_build_array(metadata->'source_locator')
                   )
             WHERE locator IS NULL
               AND metadata ? 'source_locator';
            """
        )
    # SQLite / others: skip backfill; legacy rows keep source_locator inside chunk_metadata.


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "knowledge_chunk" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("knowledge_chunk")}
    if "locator" in existing:
        op.drop_column("knowledge_chunk", "locator")
    if "source_block_ids" in existing:
        op.drop_column("knowledge_chunk", "source_block_ids")
