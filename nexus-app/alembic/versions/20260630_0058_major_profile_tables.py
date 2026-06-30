"""Create Pipeline A major_profile domain tables.

Revision ID: 20260630_0058
Revises: 20260630_0057
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexus_app.enums import ChunkingStrategy, ChunkType

revision: str = "20260630_0058"
down_revision: str | None = "20260630_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for member in ChunkType:
        op.execute(
            f"ALTER TYPE chunktype ADD VALUE IF NOT EXISTS '{member.value}'"
        )
    for member in ChunkingStrategy:
        op.execute(
            f"ALTER TYPE chunkingstrategy ADD VALUE IF NOT EXISTS '{member.value}'"
        )

    op.create_table(
        "major_profile",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column(
            "asset_version_id", sa.String(36),
            sa.ForeignKey("asset_version.id"),
            nullable=False,
        ),
        sa.Column("domain_profile", sa.Text(), nullable=False),
        sa.Column("major_code", sa.Text(), nullable=False),
        sa.Column("major_name", sa.Text(), nullable=False),
        sa.Column("education_level", sa.Text(), nullable=True),
        sa.Column("basic_study_duration", sa.Text(), nullable=True),
        sa.Column("training_goal", sa.Text(), nullable=True),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="generated"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "normalized_ref_id", "major_code", "major_name",
            name="uq_mp_ref_code_name",
        ),
    )
    op.create_index("ix_mp_normalized_ref_id", "major_profile", ["normalized_ref_id"])
    op.create_index("ix_mp_asset_version_id", "major_profile", ["asset_version_id"])
    op.create_index("ix_mp_major_code", "major_profile", ["major_code"])
    op.create_index("ix_mp_major_name", "major_profile", ["major_name"])

    _create_item_table(
        "major_profile_occupation",
        extra_columns=[
            sa.Column("normalized_name", sa.Text(), nullable=True),
            sa.Column("occupation_type", sa.Text(), nullable=False, server_default="unknown"),
        ],
    )
    op.create_index(
        "ix_mpo_normalized_name", "major_profile_occupation", ["normalized_name"]
    )

    _create_item_table("major_profile_ability")

    _create_item_table(
        "major_profile_course",
        extra_columns=[
            sa.Column("course_group", sa.Text(), nullable=False),
            sa.Column("course_type", sa.Text(), nullable=False, server_default="course"),
        ],
    )
    op.create_index("ix_mpc_course_group", "major_profile_course", ["course_group"])

    _create_item_table(
        "major_profile_certificate",
        extra_columns=[
            sa.Column(
                "certificate_type", sa.Text(), nullable=False, server_default="unknown"
            ),
        ],
    )
    _create_item_table("major_profile_continuation")


def downgrade() -> None:
    op.drop_index("ix_mpcont_normalized_ref_id", table_name="major_profile_continuation")
    op.drop_index("ix_mpcont_profile_id", table_name="major_profile_continuation")
    op.drop_table("major_profile_continuation")

    op.drop_index("ix_mpcert_normalized_ref_id", table_name="major_profile_certificate")
    op.drop_index("ix_mpcert_profile_id", table_name="major_profile_certificate")
    op.drop_table("major_profile_certificate")

    op.drop_index("ix_mpc_course_group", table_name="major_profile_course")
    op.drop_index("ix_mpc_normalized_ref_id", table_name="major_profile_course")
    op.drop_index("ix_mpc_profile_id", table_name="major_profile_course")
    op.drop_table("major_profile_course")

    op.drop_index("ix_mpa_normalized_ref_id", table_name="major_profile_ability")
    op.drop_index("ix_mpa_profile_id", table_name="major_profile_ability")
    op.drop_table("major_profile_ability")

    op.drop_index("ix_mpo_normalized_name", table_name="major_profile_occupation")
    op.drop_index("ix_mpo_normalized_ref_id", table_name="major_profile_occupation")
    op.drop_index("ix_mpo_profile_id", table_name="major_profile_occupation")
    op.drop_table("major_profile_occupation")

    op.drop_index("ix_mp_major_name", table_name="major_profile")
    op.drop_index("ix_mp_major_code", table_name="major_profile")
    op.drop_index("ix_mp_asset_version_id", table_name="major_profile")
    op.drop_index("ix_mp_normalized_ref_id", table_name="major_profile")
    op.drop_table("major_profile")


def _create_item_table(
    name: str,
    *,
    extra_columns: list[sa.Column] | None = None,
) -> None:
    prefix = {
        "major_profile_occupation": "mpo",
        "major_profile_ability": "mpa",
        "major_profile_course": "mpc",
        "major_profile_certificate": "mpcert",
        "major_profile_continuation": "mpcont",
    }[name]
    op.create_table(
        name,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("major_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "normalized_ref_id", sa.String(36),
            sa.ForeignKey("normalized_asset_ref.id"),
            nullable=False,
        ),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("locator", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=True),
        *(extra_columns or []),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(f"ix_{prefix}_profile_id", name, ["profile_id"])
    op.create_index(f"ix_{prefix}_normalized_ref_id", name, ["normalized_ref_id"])

