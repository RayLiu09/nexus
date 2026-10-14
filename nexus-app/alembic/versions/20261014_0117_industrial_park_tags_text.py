"""Store industrial park industry tags as readable text."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0117"
down_revision: str | None = "20261013_0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    op.add_column("industrial_park", sa.Column("industry_tags_text", sa.Text(), nullable=True))
    parks = sa.table(
        "industrial_park",
        sa.column("id", sa.String()),
        sa.column("industry_tags", sa.JSON()),
        sa.column("industry_tags_text", sa.Text()),
    )
    for park_id, tags in connection.execute(sa.select(parks.c.id, parks.c.industry_tags)):
        connection.execute(
            parks.update().where(parks.c.id == park_id).values(
                industry_tags_text="、".join(tags or [])
            )
        )
    with op.batch_alter_table("industrial_park") as batch:
        batch.drop_column("industry_tags")
        batch.alter_column("industry_tags_text", new_column_name="industry_tags", nullable=False)


def downgrade() -> None:
    connection = op.get_bind()
    op.add_column("industrial_park", sa.Column("industry_tags_json", sa.JSON(), nullable=True))
    parks = sa.table(
        "industrial_park",
        sa.column("id", sa.String()),
        sa.column("industry_tags", sa.Text()),
        sa.column("industry_tags_json", sa.JSON()),
    )
    for park_id, tags in connection.execute(sa.select(parks.c.id, parks.c.industry_tags)):
        connection.execute(
            parks.update().where(parks.c.id == park_id).values(
                industry_tags_json=tags.split("、") if tags else []
            )
        )
    with op.batch_alter_table("industrial_park") as batch:
        batch.drop_column("industry_tags")
        batch.alter_column("industry_tags_json", new_column_name="industry_tags", nullable=False)
