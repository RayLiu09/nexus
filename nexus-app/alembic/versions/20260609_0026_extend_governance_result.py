"""Add rules_version_id FK to governance_result and extend AuditEventType

Changes:
- Add governance_result.rules_version_id FK → governance_rules_version.id
- Extend AuditEventType with 5 new governance management events

Revision ID: 20260609_0026
Revises: 20260609_0025
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0026"
down_revision: str | None = "20260609_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extend AuditEventType with governance rules/prompt management events
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
        "'GovernanceRulesVersionCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
        "'GovernanceRulesVersionArchived'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
        "'GovernancePromptTemplateCreated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
        "'GovernancePromptTemplateUpdated'"
    )
    op.execute(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
        "'GovernancePromptTemplateDisabled'"
    )

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "governance_result" not in tables:
        # Table doesn't exist — nothing to migrate (fresh DB from models)
        return

    op.add_column(
        "governance_result",
        sa.Column(
            "rules_version_id",
            sa.String(36),
            sa.ForeignKey("governance_rules_version.id"),
            nullable=True,
            comment="FK to governance_rules_version used at decision time",
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "governance_result_rules_version_id_fkey",
        "governance_result",
        type_="foreignkey",
    )
    op.drop_column("governance_result", "rules_version_id")
