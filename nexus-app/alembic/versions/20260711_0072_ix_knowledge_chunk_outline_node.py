"""Add ix_knowledge_chunk_outline_node_id — v1.3 PR-7b chunk lift.

Enables cheap reverse lookup for the outline-node → chunk mapping used
by the unstructured executor's Phase A when
``task_outline_context`` runs a tag_filter narrowed to
``OUTLINE_NODE``.  Without this index the ``knowledge_outline_node_id
IN (…)`` clause would sequentially scan every chunk in the ref.

The column is nullable — record-type chunks and legacy rows don't
carry the FK.  The index still helps because both PostgreSQL and
SQLite skip NULLs during equality/IN scans.

Revision ID: 20260711_0072
Revises: 20260711_0071
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260711_0072"
down_revision: str | None = "20260711_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
