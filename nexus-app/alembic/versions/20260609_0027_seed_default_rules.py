"""Seed default governance rules from Excel into governance_rules_version table.

Reads ``docs/ai-governance/20260605数据清单.xlsx`` and inserts the first
``GovernanceRulesVersion`` record (version=1, status=active).

This is a ONE-TIME data migration.  It should run after the table is created
(0024) and before any application startup that reads governance rules.

Revision ID: 20260609_0027
Revises: 20260609_0026
Create Date: 2026-06-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260609_0027"
down_revision: str | None = "20260609_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    import json

    from nexus_app.ai_governance.seed_data import build_rules_content

    rules_content = build_rules_content()

    op.execute(
        """
        INSERT INTO governance_rules_version
            (id, version, status, rules_content, schema_version,
             change_summary, created_by, trace_id, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 1, 'active',
             :rules_json::jsonb, :schema_version,
             'Initial seed from 20260605数据清单.xlsx', 'system', 'seed_0027',
             now(), now())
        """,
        {
            "rules_json": json.dumps(rules_content, ensure_ascii=False),
            "schema_version": rules_content["schema_version"],
        },
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM governance_rules_version WHERE trace_id = 'seed_0027'"
    )
