"""Seed default governance prompt templates into governance_prompt_template table.

Inserts 5 ``GovernancePromptTemplate`` records (one per task type, all status=active,
template_version=1) from the built-in ``default_prompts.py`` constants.

This is a ONE-TIME data migration.  It should run after the table is created
(0025) and after rules seed (0027).

Revision ID: 20260609_0028
Revises: 20260609_0027
Create Date: 2026-06-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260609_0028"
down_revision: str | None = "20260609_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from nexus_app.ai_governance.default_prompts import DEFAULT_PROMPTS

    for task_type, cfg in DEFAULT_PROMPTS.items():
        op.execute(
            """
            INSERT INTO governance_prompt_template
                (id, task_type, template_name, template_version, status,
                 prompt_template, output_schema_version,
                 litellm_model_alias, temperature, max_input_tokens,
                 redaction_policy, change_summary, created_by, trace_id,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :task_type, :template_name, 1, 'active',
                 :prompt_template, :output_schema_version,
                 :litellm_model_alias, :temperature, :max_input_tokens,
                 :redaction_policy, 'Initial seed from default_prompts.py',
                 'system', :trace_id, now(), now())
            """,
            parameters={
                "task_type": task_type,
                "template_name": cfg["template_name"],
                "prompt_template": cfg["prompt_template"],
                "output_schema_version": cfg["output_schema_version"],
                "litellm_model_alias": cfg["litellm_model_alias"],
                "temperature": cfg["temperature"],
                "max_input_tokens": cfg["max_input_tokens"],
                "redaction_policy": cfg["redaction_policy"],
                "trace_id": f"seed_0028_{task_type}",
            },
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM governance_prompt_template WHERE trace_id LIKE 'seed_0028_%'"
    )
