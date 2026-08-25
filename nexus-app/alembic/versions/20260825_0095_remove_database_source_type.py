"""Remove the external database data-source connector.

Existing database source rows are deliberately not removed by this migration.
Operators must archive or migrate them before the enum can be narrowed.

Revision ID: 20260825_0095
Revises: 20260824_0094
Create Date: 2026-08-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_0095"
down_revision: str | None = "20260824_0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("data_source", "ingest_batch", "raw_object")
_CURRENT_VALUES = "'file_upload', 'nas', 'crawler', 'webhook'"
_LEGACY_VALUES = "'file_upload', 'nas', 'crawler', 'database', 'webhook'"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    legacy_rows = sum(
        int(
            bind.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {table} "
                    "WHERE source_type::text = 'database'"
                )
            ).scalar_one()
        )
        for table in _TABLES
    )
    if legacy_rows:
        raise RuntimeError(
            "Cannot remove datasourcetype.database while legacy database-source "
            "rows exist. Archive or migrate matching data_source, ingest_batch, "
            "and raw_object rows before rerunning this migration."
        )

    op.execute("ALTER TYPE datasourcetype RENAME TO datasourcetype_legacy")
    op.execute(f"CREATE TYPE datasourcetype AS ENUM ({_CURRENT_VALUES})")
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN source_type TYPE datasourcetype "
            "USING source_type::text::datasourcetype"
        )
    op.execute("DROP TYPE datasourcetype_legacy")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TYPE datasourcetype RENAME TO datasourcetype_without_database")
    op.execute(f"CREATE TYPE datasourcetype AS ENUM ({_LEGACY_VALUES})")
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN source_type TYPE datasourcetype "
            "USING source_type::text::datasourcetype"
        )
    op.execute("DROP TYPE datasourcetype_without_database")
