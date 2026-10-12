"""Retire the old job-demand Pipeline B extraction and Prompt seed rows."""

from collections.abc import Sequence
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20261012_0115"
down_revision: str | None = "20261012_0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # Remove immutable seed rows for the retired job-demand AI stages. These
    # rows are configuration, not business data, so deleting them prevents a
    # later reseed or runtime lookup from reviving the path.
    bind.execute(
        sa.text(
            "DELETE FROM ai_analysis_rules "
            "WHERE rule_set_code LIKE 'occupation.job_demand.%' "
            "OR scenario LIKE 'job_demand_%'"
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM ai_prompt_profile "
            "WHERE profile_name LIKE 'occupation.job_demand.%' "
            "OR scenario LIKE 'job_demand_%'"
        )
    )

    # Governance versions are immutable. Archive the active version and add a
    # new active version without the retired classification.
    rows = bind.execute(
        sa.text(
            "SELECT id, rules_content FROM governance_rules_version "
            "WHERE status = 'active'"
        )
    ).fetchall()
    for row in rows:
        content = row.rules_content
        if isinstance(content, str):
            content = json.loads(content)
        if not isinstance(content, dict):
            continue
        classifications = content.get("classifications")
        if not isinstance(classifications, list):
            continue
        filtered = [
            item for item in classifications
            if not (isinstance(item, dict) and item.get("code") == "job_demand")
        ]
        if len(filtered) == len(classifications):
            continue
        content = {**content, "classifications": filtered}
        bind.execute(
            sa.text(
                "UPDATE governance_rules_version SET status = 'archived', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
            ),
            {"id": row.id},
        )
        next_version = int(
            bind.execute(
                sa.text("SELECT COALESCE(MAX(version), 0) + 1 FROM governance_rules_version")
            ).scalar_one()
        )
        bind.execute(
            sa.text(
                "INSERT INTO governance_rules_version "
                "(id, version, status, rules_content, schema_version, "
                "change_summary, created_by, trace_id, created_at, updated_at) "
                "VALUES (:id, :version, 'active', :content, :schema_version, "
                ":summary, 'system', 'retire_job_demand_pipeline_b', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ).bindparams(sa.bindparam("content", type_=sa.JSON)),
            {
                "id": str(uuid4()),
                "version": next_version,
                "content": content,
                "schema_version": content.get("schema_version", "3.0"),
                "summary": "Retire job-demand crawler data from Pipeline B and AI governance",
            },
        )


def downgrade() -> None:
    # Retired seed content is intentionally not restored. Reintroducing it
    # would make crawler job data eligible for the removed Pipeline B path.
    pass
