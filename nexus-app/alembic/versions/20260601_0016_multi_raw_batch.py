"""Week 5: Multi-raw batch support.

Adds:
- ingest_batch.batch_status_detail (JSONB): per-raw-object status snapshot
- raw_object.file_idempotency_key (String, nullable): caller key for append
- unique (batch_id, file_idempotency_key) on raw_object
- ingest_batch_status enum: 'open' value (for not-yet-submitted batches)

Revision ID: 20260601_0016
Revises: 20260522_0015
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260601_0016"
down_revision: str | None = "20260522_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 1. Add the new enum value (PostgreSQL only; SQLite uses CHECK)
    if is_pg:
        # ALTER TYPE ... ADD VALUE must run outside a transaction block in older
        # Postgres versions. Alembic's autocommit_block handles this when needed.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE ingestbatchstatus ADD VALUE IF NOT EXISTS 'open'")

    # 2. ingest_batch.batch_status_detail
    op.add_column(
        "ingest_batch",
        sa.Column(
            "batch_status_detail",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="Per-raw-object status snapshot keyed by raw_object_id; updated by aggregator.",
        ),
    )
    op.alter_column("ingest_batch", "batch_status_detail", server_default=None)

    # 3. raw_object.file_idempotency_key + unique constraint
    op.add_column(
        "raw_object",
        sa.Column(
            "file_idempotency_key",
            sa.String(length=128),
            nullable=True,
            comment="Caller-supplied idempotency key for multi-raw batch file append; "
            "NULL for legacy single-file ingest.",
        ),
    )
    op.create_unique_constraint(
        "uq_raw_object_batch_file_idem",
        "raw_object",
        ["batch_id", "file_idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_raw_object_batch_file_idem", "raw_object", type_="unique")
    op.drop_column("raw_object", "file_idempotency_key")
    op.drop_column("ingest_batch", "batch_status_detail")
    # Note: dropping a value from a PostgreSQL enum is not natively supported.
    # 'open' is left in the enum on downgrade — operationally harmless.
