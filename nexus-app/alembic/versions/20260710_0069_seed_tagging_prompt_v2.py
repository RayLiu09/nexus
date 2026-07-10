"""Seed tagging prompt v2 (v1.3 §4.1 structured 7-category output).

Bumps ``governance_prompt_template`` row for ``task_type='tagging'`` from
``template_version=1`` to ``template_version=2``:

* Archive the current v1 row (status → ``archived``).
* Insert a fresh v2 row (status → ``active``) using ``V1_3_PROMPT_UPGRADES``
  from :mod:`nexus_app.ai_governance.default_prompts`.

The GovernancePromptRegistry looks up prompts by ``(task_type, status=active)``
so no application code changes are required — the next
``run_governance_multi`` will automatically pick up v2 for the tagging stage.

Downgrade re-activates v1 and deletes v2 by its migration-owned
``trace_id='seed_0069_tagging'``.

Revision ID: 20260710_0069
Revises: 20260709_0068
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0069"
down_revision: str | None = "20260709_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEED_TRACE_ID = "seed_0069_tagging"
_TASK_TYPE = "tagging"
_NEW_VERSION = 2


def upgrade() -> None:
    from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

    upgrade_cfg = V1_3_PROMPT_UPGRADES[_TASK_TYPE]

    bind = op.get_bind()

    # 1. Archive the previously-active tagging row (if any).  Match on
    #    (task_type, status='active') — the partial-unique index guarantees
    #    at most one such row exists.
    bind.execute(
        sa.text(
            """
            UPDATE governance_prompt_template
               SET status = 'archived', updated_at = now()
             WHERE task_type = :task_type AND status = 'active'
            """
        ).bindparams(sa.bindparam("task_type", type_=sa.String)),
        {"task_type": _TASK_TYPE},
    )

    # 2. Insert v2 as the new active row.
    bind.execute(
        sa.text(
            """
            INSERT INTO governance_prompt_template
                (id, task_type, template_name, template_version, status,
                 prompt_template, output_schema_version,
                 litellm_model_alias, temperature, max_input_tokens,
                 redaction_policy, change_summary,
                 created_by, trace_id, created_at, updated_at)
            VALUES
                (gen_random_uuid(), :task_type, :template_name, :template_version, 'active',
                 :prompt_template, :output_schema_version,
                 :litellm_model_alias, :temperature, :max_input_tokens,
                 :redaction_policy, :change_summary,
                 'system', :trace_id, now(), now())
            """
        ).bindparams(
            sa.bindparam("task_type", type_=sa.String),
            sa.bindparam("template_name", type_=sa.String),
            sa.bindparam("template_version", type_=sa.Integer),
            sa.bindparam("prompt_template", type_=sa.Text),
            sa.bindparam("output_schema_version", type_=sa.String),
            sa.bindparam("litellm_model_alias", type_=sa.String),
            sa.bindparam("temperature", type_=sa.Float),
            sa.bindparam("max_input_tokens", type_=sa.Integer),
            sa.bindparam("redaction_policy", type_=sa.String),
            sa.bindparam("change_summary", type_=sa.String),
            sa.bindparam("trace_id", type_=sa.String),
        ),
        {
            "task_type": _TASK_TYPE,
            "template_name": upgrade_cfg["template_name"],
            "template_version": _NEW_VERSION,
            "prompt_template": upgrade_cfg["prompt_template"],
            "output_schema_version": upgrade_cfg["output_schema_version"],
            "litellm_model_alias": upgrade_cfg["litellm_model_alias"],
            "temperature": upgrade_cfg["temperature"],
            "max_input_tokens": upgrade_cfg["max_input_tokens"],
            "redaction_policy": upgrade_cfg["redaction_policy"],
            "change_summary": upgrade_cfg["change_summary"],
            "trace_id": _SEED_TRACE_ID,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Remove the v2 row this migration inserted (match on our own
    #    trace_id so business-expert-authored intermediate bumps are
    #    left untouched).
    bind.execute(
        sa.text(
            "DELETE FROM governance_prompt_template WHERE trace_id = :tid"
        ).bindparams(sa.bindparam("tid", type_=sa.String)),
        {"tid": _SEED_TRACE_ID},
    )

    # 2. Restore v1 as active.  If a business-expert-authored version
    #    exists in-between (unusual), the operator must resolve the
    #    active state manually.
    bind.execute(
        sa.text(
            """
            UPDATE governance_prompt_template
               SET status = 'active', updated_at = now()
             WHERE task_type = :task_type
               AND template_version = 1
               AND status = 'archived'
            """
        ).bindparams(sa.bindparam("task_type", type_=sa.String)),
        {"task_type": _TASK_TYPE},
    )
