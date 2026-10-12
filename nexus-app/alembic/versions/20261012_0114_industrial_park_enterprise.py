"""Add Asset Center industrial park and enterprise projections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_0114"
down_revision: str | None = "20261010_0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "industrial_park",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("source_park_id", sa.String(128), nullable=False),
        sa.Column("park_name", sa.Text(), nullable=False),
        sa.Column("industry_tags", sa.JSON(), nullable=False),
        sa.Column("introduction", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_park_id", name="uq_industrial_park_source_id"),
    )
    op.create_index("ix_industrial_park_name", "industrial_park", ["park_name"])
    op.create_table(
        "enterprise",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("industrial_park_id", sa.String(36), nullable=True),
        sa.Column("source_record_key", sa.String(128), nullable=False),
        sa.Column("enterprise_name", sa.Text(), nullable=False),
        sa.Column("business_scope", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["industrial_park_id"], ["industrial_park.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_record_key", name="uq_enterprise_source_record"),
    )
    op.create_index("ix_enterprise_name", "enterprise", ["enterprise_name"])
    op.create_index("ix_enterprise_park_id", "enterprise", ["industrial_park_id"])


def downgrade() -> None:
    op.drop_index("ix_enterprise_park_id", table_name="enterprise")
    op.drop_index("ix_enterprise_name", table_name="enterprise")
    op.drop_table("enterprise")
    op.drop_index("ix_industrial_park_name", table_name="industrial_park")
    op.drop_table("industrial_park")
