"""Restrict tag_asset_index to document refs and outline nodes.

Pipeline B structured records are queried through their domain tables and no
longer participate in tag semantic retrieval. Remove their historical index
rows while preserving document governance tags and outline-node tags.

Revision ID: 20260730_0080
Revises: 20260729_0079
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260730_0080"
down_revision: str | None = "20260729_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RETIRED_TARGET_TYPES = (
    "job_demand_record",
    "job_demand_requirement_item",
    "major_distribution_record",
    "occupational_ability_item",
)


def upgrade() -> None:
    op.execute(
        "DELETE FROM tag_asset_index "
        "WHERE target_type IN ("
        + ", ".join(f"'{value}'" for value in _RETIRED_TARGET_TYPES)
        + ")"
    )


def downgrade() -> None:
    # The removed projections are derived data and cannot be reconstructed
    # faithfully after their source contract has been retired.
    return
