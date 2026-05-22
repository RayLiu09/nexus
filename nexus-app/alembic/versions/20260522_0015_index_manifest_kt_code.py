"""IndexManifest: add knowledge_type_code with unique (ref, kt) constraint (Review 1.5).

Revision ID: 20260522_0015
Revises: 20260521_0014
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0015"
down_revision: str | None = "20260521_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: add nullable column so existing rows survive
    op.add_column(
        "index_manifest",
        sa.Column("knowledge_type_code", sa.String(length=64), nullable=True),
    )

    # Step 2: backfill — historical rows predate the multi-KB design.
    # Mark them with a sentinel so the NOT NULL constraint and uniqueness
    # check below can proceed; operators should re-index affected refs.
    op.execute(
        "UPDATE index_manifest "
        "SET knowledge_type_code = 'legacy_unknown' "
        "WHERE knowledge_type_code IS NULL"
    )

    # Step 3: enforce NOT NULL + supporting index + unique constraint
    op.alter_column(
        "index_manifest", "knowledge_type_code", nullable=False,
    )
    op.create_index(
        "ix_index_manifest_kt_code", "index_manifest", ["knowledge_type_code"],
    )
    op.create_unique_constraint(
        "uq_index_manifest_ref_kt",
        "index_manifest",
        ["normalized_ref_id", "knowledge_type_code"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_index_manifest_ref_kt", "index_manifest", type_="unique")
    op.drop_index("ix_index_manifest_kt_code", table_name="index_manifest")
    op.drop_column("index_manifest", "knowledge_type_code")
