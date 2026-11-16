"""Speed normalized-ref catalog tag predicates by target and tag type.

Revision ID: 20261116_0131
Revises: 20261102_0130
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261116_0131"
down_revision: str | None = "20261102_0130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_tai_target_tag_type",
        "tag_asset_index",
        ["target_type", "target_id", "tag_type"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_tai_target_tag_type", table_name="tag_asset_index")
