"""Create governance_rules_version table

Changes:
- Create GovernanceRulesVersionStatus enum
- Create governance_rules_version table with partial unique index on active

Revision ID: 20260609_0024
Revises: 20260607_0023
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0024"
down_revision: str | None = "20260607_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE governancerulesversionstatus AS ENUM ('active', 'archived')"
    )

    op.create_table(
        "governance_rules_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="governancerulesversionstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("rules_content", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("change_summary", sa.String(512), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_grv_status", "governance_rules_version", ["status"])
    # Partial unique index: only one active version at a time
    op.execute(
        "CREATE UNIQUE INDEX uq_grv_active ON governance_rules_version (status) "
        "WHERE status = 'active'"
    )


def downgrade() -> None:
    op.drop_table("governance_rules_version")
    op.execute("DROP TYPE IF EXISTS governancerulesversionstatus")
