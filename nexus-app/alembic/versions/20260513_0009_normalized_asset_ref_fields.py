"""normalized_asset_ref: add governance/quality/lineage/source fields

Changes:
- normalized_asset_ref: add source_type, content_type, title, language,
  governance (JSONB), quality (JSONB), lineage (JSONB)
- normalized_asset_ref: rename metadata_summary semantics (no schema change,
  content now holds source/business/temporal metadata per spec)

Revision ID: 20260513_0009
Revises: 20260508_0008
Create Date: 2026-05-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260513_0009"
down_revision: str | None = "20260508_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLS = [
    ("source_type", sa.String(40), True),
    ("content_type", sa.String(40), True),
    ("title", sa.String(512), True),
    ("language", sa.String(16), True),
]
_NEW_JSON_COLS = ["governance", "quality", "lineage"]


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        for col_name, col_type, nullable in _NEW_COLS:
            op.add_column("normalized_asset_ref", sa.Column(col_name, col_type, nullable=nullable))
        for col_name in _NEW_JSON_COLS:
            op.add_column(
                "normalized_asset_ref",
                sa.Column(col_name, postgresql.JSONB, nullable=False, server_default="{}"),
            )
    else:
        with op.batch_alter_table("normalized_asset_ref") as batch_op:
            for col_name, col_type, nullable in _NEW_COLS:
                batch_op.add_column(sa.Column(col_name, col_type, nullable=nullable))
            for col_name in _NEW_JSON_COLS:
                batch_op.add_column(
                    sa.Column(col_name, sa.JSON, nullable=False, server_default="{}")
                )


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    drop_cols = [c for c, _, _ in _NEW_COLS] + _NEW_JSON_COLS

    if is_pg:
        for col_name in drop_cols:
            op.drop_column("normalized_asset_ref", col_name)
    else:
        with op.batch_alter_table("normalized_asset_ref") as batch_op:
            for col_name in drop_cols:
                batch_op.drop_column(col_name)
