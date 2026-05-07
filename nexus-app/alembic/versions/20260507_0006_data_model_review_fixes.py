"""data model review fixes (v2.4 review cycle)

Changes:
- OrgUnit.status: PrincipalStatus → new OrgUnitStatus (active, disabled)
- PrincipalStatus: remove 'archived' value (user_account only)
- ApiCaller: drop status column, add expired_at
- IngestBatch: rename submitted_by_user_id → owner_user_id
- JobStage.status: JobStatus → new StageStatus (running, succeeded, failed)

Revision ID: 20260507_0006
Revises: 20260506_0005
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260507_0006"
down_revision: str | None = "20260506_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        # 1. New enum types
        op.execute("CREATE TYPE orgunitstatus AS ENUM ('active', 'disabled')")
        op.execute("CREATE TYPE stagestatus AS ENUM ('running', 'succeeded', 'failed')")
        op.execute("CREATE TYPE principalstatus_new AS ENUM ('active', 'disabled')")

        # 2. Migrate data before type changes
        op.execute("UPDATE org_unit SET status = 'disabled' WHERE status = 'archived'")
        op.execute("UPDATE user_account SET status = 'disabled' WHERE status = 'archived'")

        # 3. Change column types
        op.execute(
            "ALTER TABLE org_unit ALTER COLUMN status TYPE orgunitstatus "
            "USING status::text::orgunitstatus"
        )
        op.execute(
            "ALTER TABLE user_account ALTER COLUMN status TYPE principalstatus_new "
            "USING status::text::principalstatus_new"
        )
        op.execute(
            "ALTER TABLE job_stage ALTER COLUMN status TYPE stagestatus "
            "USING status::text::stagestatus"
        )

    # 4. ApiCaller: drop status, add expired_at (dialect-agnostic)
    op.drop_column("api_caller", "status")
    op.add_column(
        "api_caller",
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
    )

    if is_pg:
        # 5. Clean up old principalstatus type (now only unreferenced after api_caller.status drop)
        op.execute("DROP TYPE principalstatus")
        op.execute("ALTER TYPE principalstatus_new RENAME TO principalstatus")

    # 6. Rename submitted_by_user_id → owner_user_id (batch_alter handles SQLite recreation)
    with op.batch_alter_table("ingest_batch") as batch_op:
        batch_op.alter_column("submitted_by_user_id", new_column_name="owner_user_id")


def downgrade() -> None:
    with op.batch_alter_table("ingest_batch") as batch_op:
        batch_op.alter_column("owner_user_id", new_column_name="submitted_by_user_id")

    op.drop_column("api_caller", "expired_at")
    op.add_column(
        "api_caller",
        sa.Column(
            "status",
            sa.Enum("active", "disabled", "archived", name="principalstatus"),
            nullable=False,
            server_default="active",
        ),
    )

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE job_stage ALTER COLUMN status TYPE jobstatus "
            "USING status::text::jobstatus"
        )
        op.execute("DROP TYPE stagestatus")
        op.execute(
            "CREATE TYPE principalstatus_old AS ENUM ('active', 'disabled', 'archived')"
        )
        op.execute(
            "ALTER TABLE user_account ALTER COLUMN status TYPE principalstatus_old "
            "USING status::text::principalstatus_old"
        )
        op.execute(
            "ALTER TABLE org_unit ALTER COLUMN status TYPE principalstatus_old "
            "USING status::text::principalstatus_old"
        )
        op.execute("DROP TYPE principalstatus")
        op.execute("ALTER TYPE principalstatus_old RENAME TO principalstatus")
        op.execute("DROP TYPE orgunitstatus")
