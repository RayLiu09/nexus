"""Add `job.payload_schema_version` for forward compatibility on payload shape.

Revision ID: 20260605_0019
Revises: 20260603_0018
Create Date: 2026-06-05

Rationale: a bare `Job.payload` JSON column doesn't tell workers whether they
understand the row. After this column lands, every new job is stamped with the
schema version the producer was running; workers refuse versions outside
`SUPPORTED_JOB_PAYLOAD_VERSIONS` and dead-letter the row. Backfill defaults
existing rows to `"v1"` — that's the only payload shape that has ever shipped
so far, so the backfill is exact, not a guess.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260605_0019"
down_revision: str | None = "20260603_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add as nullable first so the column can be created on a non-empty table,
    # backfill, then enforce NOT NULL with the chosen default.
    op.add_column(
        "job",
        sa.Column(
            "payload_schema_version",
            sa.String(length=16),
            nullable=True,
        ),
    )
    op.execute("UPDATE job SET payload_schema_version = 'v1' WHERE payload_schema_version IS NULL")
    op.alter_column(
        "job",
        "payload_schema_version",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="v1",
    )


def downgrade() -> None:
    op.drop_column("job", "payload_schema_version")
