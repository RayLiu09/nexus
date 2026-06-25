"""B5.1 — seed ai_analysis_rules + 4 ai_prompt_profile rows.

Idempotent insert keyed by:
- `(rule_set_code, version)` on ai_analysis_rules
- `(profile_name, profile_version)` on ai_prompt_profile

Existing rows are NEVER mutated by re-running this migration — that's a
hard freeze rule (`docs/pipeline_b_contract_freeze.md §八`). Updates go
through a new `(rule_set_code, version)` or `(profile_name, profile_version)`
entry, not through re-seeds.

The 4 ai_analysis_rules rows + the 4 ai_prompt_profile rows are paired:
each prompt's `rules_object_code` is `<rule_set_code>:<version>` of its
companion rule set. The pairing is what lets the extraction service resolve
prompt → rule set with a single PG lookup.

Revision ID: 20260627_0047
Revises: 20260627_0046
Create Date: 2026-06-27
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
from sqlalchemy import text

from nexus_app.knowledge_extraction.rules_loader import seed_ai_analysis_rules

revision: str = "20260627_0047"
down_revision: str | None = "20260627_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 4 prompt profiles, one per (scenario, rule_set_code) pair declared in
# `config/ai_analysis_rules.json`. Kept as a const here rather than a
# separate seed file because:
# - they're tightly coupled to the rule sets (separate file would invite drift)
# - they're a one-time bootstrap, not a runtime config
# - the prompt_template strings are intentionally lean — operators are
#   expected to tune them in the console post-deploy (saving a new
#   profile_version auto-archives the existing active one)
_PROMPT_PROFILE_SEEDS: list[dict[str, object]] = [
    {
        "profile_name": "occupation.job_demand.requirement_extraction",
        "task_type": "knowledge_extraction",
        "scenario": "job_demand_requirement_extraction",
        "domain": "occupation",
        "rules_object_type": "ai_analysis_rules",
        "rules_object_code": "occupation.job_demand.requirement_extraction.rules:v1",
        "litellm_model_alias": "internal/job-extract-v1",
        "prompt_version": "1.0",
        "prompt_template": (
            "你是岗位需求结构化抽取助手。基于给定的岗位记录字段，输出 JSON "
            "items 数组，每项含 item_type / item_name / raw_text / confidence。"
            "禁止臆测、禁止跨字段编造；item_type 仅取 "
            "professional_skill / tool / certificate / professional_literacy "
            "/ work_task_candidate。输出格式严格匹配 ai_analysis_rules 中的 "
            "output_item_schema。"
        ),
        "output_schema_version": "1.0",
        "scoring_weight_version": "1.0",
        "temperature": 0.2,
        "max_input_tokens": 4096,
        "redaction_policy": "masked_content",
    },
    {
        "profile_name": "occupation.task_description_structuring",
        "task_type": "knowledge_extraction",
        "scenario": "occupational_task_description_structuring",
        "domain": "occupation",
        "rules_object_type": "ai_analysis_rules",
        "rules_object_code": "occupation.task_description_structuring.rules:v1",
        "litellm_model_alias": "internal/task-struct-v1",
        "prompt_version": "1.0",
        "prompt_template": (
            "你是岗位能力分析任务描述结构化助手。基于给定的 task_name / "
            "task_description，抽取 target_roles / tools / environment / "
            "work_modes 四类 buckets。每个字符串不超过 64 字符；保留原文中 "
            "①②③ 等符号语义；不允许臆测。输出 JSON 对象严格匹配 "
            "output_item_schema。"
        ),
        "output_schema_version": "1.0",
        "scoring_weight_version": "1.0",
        "temperature": 0.2,
        "max_input_tokens": 2048,
        "redaction_policy": "masked_content",
    },
    {
        "profile_name": "occupation.job_demand.body_markdown_render",
        "task_type": "body_markdown_render",
        "scenario": "job_demand_body_markdown_render",
        "domain": "occupation",
        "rules_object_type": "ai_analysis_rules",
        "rules_object_code": "occupation.job_demand.body_markdown_render.rules:v1",
        "litellm_model_alias": "internal/markdown-render-v1",
        "prompt_version": "1.0",
        "prompt_template": (
            "你是岗位需求数据集的 Markdown 派生视图渲染助手。基于 record_body "
            "中的 dataset + records，按 markdown_skeleton 中声明的 H1 / H2 / "
            "字段块严格输出 Markdown。禁止杜撰字段、禁止改写原值、禁止翻译。"
            "超过 max_records_inline 时按 overflow_notice_template 提示。"
        ),
        "output_schema_version": "1.0",
        "scoring_weight_version": "1.0",
        "temperature": 0.0,  # markdown render — deterministic-leaning
        "max_input_tokens": 8192,
        "redaction_policy": "masked_content",
    },
    {
        "profile_name": "occupation.ability_analysis.body_markdown_render",
        "task_type": "body_markdown_render",
        "scenario": "ability_analysis_body_markdown_render",
        "domain": "occupation",
        "rules_object_type": "ai_analysis_rules",
        "rules_object_code": "occupation.ability_analysis.body_markdown_render.rules:v1",
        "litellm_model_alias": "internal/markdown-render-v1",
        "prompt_version": "1.0",
        "prompt_template": (
            "你是职业能力分析（PGSD）的 Markdown 派生视图渲染助手。基于 "
            "record_body 中的 analysis + tasks，按 markdown_skeleton 严格输出 "
            "Markdown，保持 ability_code 完全一致、保留 task_description 原文。"
            "禁止杜撰能力条目；超过 max_abilities_per_work_content_inline 时按 "
            "overflow_notice_template 提示。"
        ),
        "output_schema_version": "1.0",
        "scoring_weight_version": "1.0",
        "temperature": 0.0,
        "max_input_tokens": 8192,
        "redaction_policy": "masked_content",
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # ----- 1. ai_analysis_rules seed via loader (loads from JSON) ----------
    inserted = seed_ai_analysis_rules(bind, initialized_by="system_seed")
    if inserted:
        op.execute(
            text(
                "-- B5.1 ai_analysis_rules seed inserted "
                f"{inserted} row(s) (idempotent)"
            )
        )

    # ----- 2. ai_prompt_profile seed (4 rows) -----------------------------
    for entry in _PROMPT_PROFILE_SEEDS:
        existing = bind.execute(
            text(
                "SELECT 1 FROM ai_prompt_profile "
                "WHERE profile_name = :name AND profile_version = 1"
            ),
            {"name": entry["profile_name"]},
        ).first()
        if existing:
            continue
        bind.execute(
            text(
                """
                INSERT INTO ai_prompt_profile (
                    id, profile_name, profile_version, task_type, scenario,
                    domain, rules_object_type, rules_object_code, status,
                    litellm_model_alias, prompt_version, prompt_template,
                    output_schema_version, scoring_weight_version,
                    temperature, max_input_tokens, redaction_policy,
                    created_by, trace_id, created_at, updated_at
                ) VALUES (
                    :id, :profile_name, 1, :task_type, :scenario,
                    :domain, :rules_object_type, :rules_object_code, 'active',
                    :litellm_model_alias, :prompt_version, :prompt_template,
                    :output_schema_version, :scoring_weight_version,
                    :temperature, :max_input_tokens, :redaction_policy,
                    'system_seed', NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                **entry,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Remove the seeded prompt profiles (only the v1 rows; if operators
    # tuned a v2 the downgrade preserves it).
    for entry in _PROMPT_PROFILE_SEEDS:
        bind.execute(
            text(
                "DELETE FROM ai_prompt_profile "
                "WHERE profile_name = :name AND profile_version = 1 "
                "AND created_by = 'system_seed'"
            ),
            {"name": entry["profile_name"]},
        )
    # Remove the seeded rule sets (only system_seed-initialised rows).
    bind.execute(
        text(
            "DELETE FROM ai_analysis_rules "
            "WHERE initialized_by = 'system_seed'"
        )
    )
