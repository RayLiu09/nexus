"""Add retrieval-side AuditEventType enum values — PR-12 follow-up.

PR-12 (a49c92c) shipped ``RETRIEVAL_TAG_FILTER_APPLIED`` and
``RETRIEVAL_DAG_EXECUTED`` in the ``AuditEventType`` Python enum but
omitted the ``ALTER TYPE`` migration needed to add the values to the
Postgres side.  The M-C.3 golden harness caught this by running
against real Postgres and hitting
``invalid input value for enum auditeventtype``.

Idempotent — ``ALTER TYPE … ADD VALUE IF NOT EXISTS`` is safe to
re-run.  SQLite has no enum types so the migration is a no-op there.

Revision ID: 20260711_0073
Revises: 20260711_0072
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260711_0073"
down_revision: str | None = "20260711_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_VALUES = (
    "RetrievalTagFilterApplied",
    "RetrievalDagExecuted",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # PostgreSQL 12+ supports ALTER TYPE ADD VALUE inside a
    # transaction.  IF NOT EXISTS keeps re-runs safe.
    for value in _NEW_VALUES:
        op.execute(
            f"ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed without recreating the
    # type — not worth the churn for two additive audit codes.  The
    # values just become orphaned; leaving them in place is fine.
    return
