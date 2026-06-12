"""Sync auditeventtype enum with code-declared AuditEventType values.

Background:
- Several earlier migrations (0011, 0012, 0018, 0022, 0026, etc.) added
  values to the PostgreSQL `auditeventtype` enum via
  `ALTER TYPE ... ADD VALUE IF NOT EXISTS`.
- Databases created via `Base.metadata.create_all` + `alembic stamp head`
  (rather than running migrations from scratch) skip those ADD VALUE
  statements, so the enum can lag behind `nexus_app.enums.AuditEventType`.
- The first symptom is `POST /internal/v1/auth/login` returning 500 with
  `invalid input value for enum auditeventtype: "UserLoginSucceeded"`,
  because `audit_p1_enable` introduced the audit calls but never added the
  enum members.

This migration reconciles by issuing `ADD VALUE IF NOT EXISTS` for every
value in the Python enum. Each statement is a no-op when the value is
already present, so it is safe to apply repeatedly and on any state of
the enum.

Revision ID: 20260612_0031
Revises: 20260610_0030
Create Date: 2026-06-12
"""

from collections.abc import Sequence

from alembic import op

from nexus_app.enums import AuditEventType

revision: str = "20260612_0031"
down_revision: str | None = "20260610_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction
    # block. Follow the same pattern as migrations 0011, 0012, 0018, 0022,
    # 0026 — issue one statement per value, each idempotent via
    # `IF NOT EXISTS`.
    for member in AuditEventType:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{member.value}'"
        )


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; dropping requires recreating
    # the type and rewriting every column referencing it. Earlier ADD VALUE
    # migrations also intentionally leave downgrade empty.
    pass
