"""Support institution professional introductions in major_profile.

Revision ID: 20260820_0091
Revises: 20260820_0090
Create Date: 2026-08-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0091"
down_revision: str | None = "20260820_0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("major_profile", "major_code", existing_type=sa.Text(), nullable=True)
    op.add_column("major_profile", sa.Column("profile_source", sa.Text(), nullable=False, server_default="national_standard"))
    op.add_column("major_profile", sa.Column("institution_name", sa.Text(), nullable=True))
    op.add_column("major_profile", sa.Column("region_tags", sa.JSON(), nullable=False, server_default="[]"))
    op.create_index("ix_mp_institution_name", "major_profile", ["institution_name"])
    op.create_table(
        "major_profile_industry_partnership",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("major_profile.id", ondelete="CASCADE"), nullable=False),
        sa.Column("normalized_ref_id", sa.String(36), sa.ForeignKey("normalized_asset_ref.id"), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("locator", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("partner_name", sa.Text(), nullable=True),
        sa.Column("partnership_type", sa.Text(), nullable=False, server_default="industry_education"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_mpip_profile_id", "major_profile_industry_partnership", ["profile_id"])
    op.create_index("ix_mpip_normalized_ref_id", "major_profile_industry_partnership", ["normalized_ref_id"])
    op.create_index("ix_mpip_partner_name", "major_profile_industry_partnership", ["partner_name"])


def downgrade() -> None:
    op.drop_index("ix_mpip_partner_name", table_name="major_profile_industry_partnership")
    op.drop_index("ix_mpip_normalized_ref_id", table_name="major_profile_industry_partnership")
    op.drop_index("ix_mpip_profile_id", table_name="major_profile_industry_partnership")
    op.drop_table("major_profile_industry_partnership")
    op.drop_index("ix_mp_institution_name", table_name="major_profile")
    op.drop_column("major_profile", "region_tags")
    op.drop_column("major_profile", "institution_name")
    op.drop_column("major_profile", "profile_source")
    op.alter_column("major_profile", "major_code", existing_type=sa.Text(), nullable=False)
