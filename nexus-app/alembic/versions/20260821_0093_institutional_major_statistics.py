"""Add province and deterministic course statistic keys.

Revision ID: 20260821_0093
Revises: 20260820_0092
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0093"
down_revision: str | None = "20260820_0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("major_profile", sa.Column("province_name", sa.Text(), nullable=True))
    op.add_column("talent_training_plan", sa.Column("province_name", sa.Text(), nullable=True))
    op.add_column("major_profile_course", sa.Column("course_stat_key", sa.Text(), nullable=True))
    op.add_column("talent_training_plan_course", sa.Column("course_stat_key", sa.Text(), nullable=True))
    op.create_index("ix_mp_province_name", "major_profile", ["province_name"])
    op.create_index("ix_ttp_province_name", "talent_training_plan", ["province_name"])
    op.create_index("ix_mpc_course_stat_key", "major_profile_course", ["course_stat_key"])
    op.create_index("ix_ttpc_course_stat_key", "talent_training_plan_course", ["course_stat_key"])


def downgrade() -> None:
    op.drop_index("ix_ttpc_course_stat_key", table_name="talent_training_plan_course")
    op.drop_index("ix_mpc_course_stat_key", table_name="major_profile_course")
    op.drop_index("ix_ttp_province_name", table_name="talent_training_plan")
    op.drop_index("ix_mp_province_name", table_name="major_profile")
    op.drop_column("talent_training_plan_course", "course_stat_key")
    op.drop_column("major_profile_course", "course_stat_key")
    op.drop_column("talent_training_plan", "province_name")
    op.drop_column("major_profile", "province_name")
