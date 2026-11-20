"""Add optional crawler job metrics without backfilling historical records.

Revision ID: 20261120_0134
Revises: 20261118_0133
"""

from alembic import op
import sqlalchemy as sa


revision = "20261120_0134"
down_revision = "20261118_0133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("raw_jobs") as batch:
        batch.add_column(sa.Column("location_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("hiring_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("publish_time_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("published_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_raw_jobs_hiring_count_nonnegative", "hiring_count >= 0")


def downgrade() -> None:
    with op.batch_alter_table("raw_jobs") as batch:
        batch.drop_constraint("ck_raw_jobs_hiring_count_nonnegative", type_="check")
        batch.drop_column("published_at")
        batch.drop_column("published_date")
        batch.drop_column("publish_time_text")
        batch.drop_column("hiring_count")
        batch.drop_column("location_text")
