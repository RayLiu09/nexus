"""audit_log: extend auditeventtype enum with all current event values

Changes:
- auditeventtype: add CrossSourceDuplicateDetected, AssetVersionArchived,
  DataSourceCreated, DataSourceStatusChanged, ApiCallerCreated, ApiCallerRevoked,
  IngestValidateCompleted

Revision ID: 20260513_0010
Revises: 20260513_0009
Create Date: 2026-05-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260513_0010"
down_revision: str | None = "20260513_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Values to add — order matters for readability; PostgreSQL appends them in order.
_ADD_VALUES = [
    "CrossSourceDuplicateDetected",
    "AssetVersionArchived",
    "DataSourceCreated",
    "DataSourceStatusChanged",
    "ApiCallerCreated",
    "ApiCallerRevoked",
    "IngestValidateCompleted",
]


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return  # SQLite uses VARCHAR — no enum type to alter

    existing = {
        row[0]
        for row in conn.execute(
            __import__("sqlalchemy").text(
                "SELECT unnest(enum_range(NULL::auditeventtype))::text"
            )
        )
    }
    for value in _ADD_VALUES:
        if value not in existing:
            op.execute(f"ALTER TYPE auditeventtype ADD VALUE '{value}'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    pass
