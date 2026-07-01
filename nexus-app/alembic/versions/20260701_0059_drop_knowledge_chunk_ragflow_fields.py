"""Drop deprecated RAGFlow fields from knowledge_chunk.

Revision ID: 20260701_0059
Revises: 20260630_0058
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_0059"
down_revision: str | None = "20260630_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if "ix_knowledge_chunk_ragflow_doc" in _indexes("knowledge_chunk"):
        op.drop_index("ix_knowledge_chunk_ragflow_doc", table_name="knowledge_chunk")
    existing = _columns("knowledge_chunk")
    for column_name in ("ragflow_chunk_id", "ragflow_doc_id", "ragflow_chunk_method"):
        if column_name in existing:
            op.drop_column("knowledge_chunk", column_name)


def downgrade() -> None:
    existing = _columns("knowledge_chunk")
    if "ragflow_chunk_method" not in existing:
        op.add_column(
            "knowledge_chunk",
            sa.Column("ragflow_chunk_method", sa.String(50), nullable=True),
        )
    if "ragflow_doc_id" not in existing:
        op.add_column(
            "knowledge_chunk",
            sa.Column("ragflow_doc_id", sa.String(128), nullable=True),
        )
    if "ragflow_chunk_id" not in existing:
        op.add_column(
            "knowledge_chunk",
            sa.Column("ragflow_chunk_id", sa.String(128), nullable=True),
        )
    if "ix_knowledge_chunk_ragflow_doc" not in _indexes("knowledge_chunk"):
        op.create_index(
            "ix_knowledge_chunk_ragflow_doc",
            "knowledge_chunk",
            ["ragflow_doc_id"],
        )
