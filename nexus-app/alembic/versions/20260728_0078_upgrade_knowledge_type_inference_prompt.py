"""Replace the stale knowledge-type prompt with a canonical-code version.

The initial seed predated the ``textbook_kb`` -> ``course_textbook``
unification.  Keep that template immutable for governance-run provenance and
create v2 only when the active template still contains the retired code.

Revision ID: 20260728_0078
Revises: 20260728_0077
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_0078"
down_revision: str | None = "20260728_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TASK_TYPE = "knowledge_type_inference"
_SEED_TRACE_ID = "seed_0078_knowledge_type_inference"


def upgrade() -> None:
    from nexus_app.ai_governance.default_prompts import (
        KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2,
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE governance_prompt_template
               SET status = 'archived', updated_at = now()
             WHERE task_type = :task_type
               AND status = 'active'
               AND prompt_template LIKE '%textbook_kb%'
            """
        ).bindparams(sa.bindparam("task_type", type_=sa.String)),
        {"task_type": _TASK_TYPE},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO governance_prompt_template
                (id, task_type, template_name, template_version, status,
                 prompt_template, output_schema_version,
                 litellm_model_alias, temperature, max_input_tokens,
                 redaction_policy, change_summary,
                 created_by, trace_id, created_at, updated_at)
            SELECT gen_random_uuid(), :task_type,
                   :template_name,
                   COALESCE(MAX(template_version), 0) + 1,
                   'active', :prompt_template, :output_schema_version,
                   :litellm_model_alias, :temperature, :max_input_tokens,
                   :redaction_policy, :change_summary,
                   'system', :trace_id, now(), now()
              FROM governance_prompt_template
             WHERE task_type = :task_type
               AND NOT EXISTS (
                   SELECT 1 FROM governance_prompt_template
                    WHERE task_type = :task_type AND status = 'active'
               )
            """
        ).bindparams(sa.bindparam("task_type", type_=sa.String)),
        {
            "task_type": _TASK_TYPE,
            "template_name": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2["template_name"],
            "prompt_template": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2["prompt_template"],
            "output_schema_version": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2[
                "output_schema_version"
            ],
            "litellm_model_alias": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2[
                "litellm_model_alias"
            ],
            "temperature": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2["temperature"],
            "max_input_tokens": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2[
                "max_input_tokens"
            ],
            "redaction_policy": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2[
                "redaction_policy"
            ],
            "change_summary": KNOWLEDGE_TYPE_INFERENCE_PROMPT_V2["change_summary"],
            "trace_id": _SEED_TRACE_ID,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM governance_prompt_template WHERE trace_id = :trace_id"
        ),
        {"trace_id": _SEED_TRACE_ID},
    )
    bind.execute(
        sa.text(
            """
            UPDATE governance_prompt_template
               SET status = 'active', updated_at = now()
             WHERE task_type = :task_type
               AND template_version = 1
               AND status = 'archived'
               AND NOT EXISTS (
                   SELECT 1 FROM governance_prompt_template
                    WHERE task_type = :task_type AND status = 'active'
               )
            """
        ).bindparams(sa.bindparam("task_type", type_=sa.String)),
        {"task_type": _TASK_TYPE},
    )
