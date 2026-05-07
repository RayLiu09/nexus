"""v2.6 pipeline routing: unique constraint on document_asset source key

Changes:
- document_asset: drop non-unique index ix_document_asset_source,
  add unique constraint uq_document_asset_source_key on (data_source_id, source_object_key)

Revision ID: 20260507_0007
Revises: 20260507_0006
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260507_0007"
down_revision: str | None = "20260507_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        op.drop_index("ix_document_asset_source", table_name="document_asset")
        op.create_unique_constraint(
            "uq_document_asset_source_key",
            "document_asset",
            ["data_source_id", "source_object_key"],
        )
    else:
        with op.batch_alter_table("document_asset") as batch_op:
            batch_op.drop_index("ix_document_asset_source")
            batch_op.create_unique_constraint(
                "uq_document_asset_source_key",
                ["data_source_id", "source_object_key"],
            )


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        op.drop_constraint("uq_document_asset_source_key", "document_asset", type_="unique")
        op.create_index(
            "ix_document_asset_source",
            "document_asset",
            ["data_source_id", "source_object_key"],
        )
    else:
        with op.batch_alter_table("document_asset") as batch_op:
            batch_op.drop_constraint("uq_document_asset_source_key", type_="unique")
            batch_op.create_index(
                "ix_document_asset_source",
                ["data_source_id", "source_object_key"],
            )
