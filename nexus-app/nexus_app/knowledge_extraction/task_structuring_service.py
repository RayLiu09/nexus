"""LLM-driven structuring of `occupational_work_task.task_description`.

Per design decision 18/19: each task's free-text `task_description` (often
contains ①②③ enumerated steps) is structured into four typed buckets by a
dedicated LLM scenario, reusing the same `ai_prompt_profile` +
`ai_analysis_rules` infrastructure as `service.py` but with a different
output shape (one structured object per task vs. a list of items per
record).

Trigger point: `worker/runner.py:_run_domain_normalize`, after the B6
ability_analysis writer succeeds AND after B5.3 body_markdown rendering.
Skipped quietly when LLM / rule_set / prompt are unavailable.

Buckets (frozen by `config/ai_analysis_rules.json::occupation.task_description_structuring.rules`):
- `target_roles`  — who performs the task
- `tools`         — concrete tools / platforms named in the description
- `environment`   — context where the work happens
- `work_modes`    — execution patterns (e.g. "迭代式", "在线")

The structured object replaces the empty `{}` that the B6 writer wrote so
B7 governance + B9 console see structured data once the LLM run completes.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.ai_governance.model_alias import resolve_model_alias
from nexus_app.enums import PromptProfileStatus

logger = logging.getLogger(__name__)

SCENARIO: str = "occupational_task_description_structuring"

# Exact set of output buckets the rule_set requires. Order here is fixed so
# the JSONB column has a stable key order across writes — easier for
# downstream consumers to diff / compare.
_BUCKETS: tuple[str, ...] = ("target_roles", "tools", "environment", "work_modes")

# Hard limit per single bucket string (mirrors output_item_schema maxLength).
_MAX_STRING_CHARS = 64
# Per-task input cap — protects the prompt from runaway descriptions. B5.4
# truncates rather than rejects, since dropping a real task is worse than
# losing the tail of a long description.
_MAX_DESCRIPTION_CHARS_FOR_PROMPT = 4000


class RejectReason:
    SCHEMA_INVALID = "schema_invalid"
    GUARDRAIL_EMPTY_ALL_BUCKETS = "guardrail_empty_all_buckets"
    GUARDRAIL_STRING_OVER_64_CHARS = "guardrail_string_over_64_chars"


@dataclass(frozen=True)
class TaskStructuringTaskResult:
    """Per-task outcome for the audit / aggregate."""
    task_id: str
    persisted: bool = False
    rejected: bool = False
    rejected_reason: str | None = None
    structured: dict[str, list[str]] | None = None


@dataclass(frozen=True)
class _PreparedTask:
    task_id: str
    task_code: str | None
    task_name: str | None
    description: str


@dataclass(frozen=True)
class TaskStructuringResult:
    """Analysis-level summary returned to the worker."""
    analysis_id: str
    rule_set_id: str
    prompt_profile_id: str
    tasks_processed: int = 0
    tasks_structured: int = 0
    tasks_rejected: int = 0
    quality_summary: dict[str, int] = field(default_factory=dict)
    skipped: bool = False
    skipped_reason: str | None = None


def structure_task_descriptions_for_analysis(
    session: Session,
    analysis: models.OccupationalAbilityAnalysis,
    *,
    llm_client: LiteLLMClientProtocol | None,
) -> TaskStructuringResult:
    """Run LLM structuring for every task in `analysis`.

    Caller owns commit (mirrors B5.2 service contract). On any task-level
    failure we drop just that task's update — other tasks still complete.
    """
    if llm_client is None:
        return _skipped(analysis, "llm_client_unavailable")

    rule_set = _load_active_rule_set(session)
    if rule_set is None:
        return _skipped(analysis, "rule_set_not_seeded")
    prompt = _load_active_prompt_profile(session)
    if prompt is None:
        return _skipped(analysis, "prompt_profile_not_seeded")

    tasks = list(
        session.scalars(
            select(models.OccupationalWorkTask).where(
                models.OccupationalWorkTask.analysis_id == analysis.id
            )
        )
    )
    if not tasks:
        return TaskStructuringResult(
            analysis_id=analysis.id,
            rule_set_id=rule_set.id,
            prompt_profile_id=prompt.id,
            tasks_processed=0,
        )

    analysis_id = analysis.id
    rule_set_id = rule_set.id
    prompt_profile_id = prompt.id
    prompt_template = prompt.prompt_template
    model_alias = resolve_model_alias(prompt)
    temperature = float(prompt.temperature)
    max_tokens = int(prompt.max_input_tokens)
    prepared_tasks = [
        _PreparedTask(
            task_id=task.id,
            task_code=task.task_code,
            task_name=task.task_name,
            description=task.task_description or "",
        )
        for task in tasks
    ]

    # Do not let the synchronous LiteLLM requests retain the worker's open
    # transaction. The prepared tasks and prompt are immutable snapshots; the
    # result is reloaded and written in the short transaction below.
    session.commit()
    per_task_results = [
        _structure_task(
            task=task,
            prompt_template=prompt_template,
            model_alias=model_alias,
            temperature=temperature,
            max_tokens=max_tokens,
            llm_client=llm_client,
        )
        for task in prepared_tasks
    ]
    tasks_by_id = {
        task.id: task
        for task in session.scalars(
            select(models.OccupationalWorkTask).where(
                models.OccupationalWorkTask.id.in_([task.task_id for task in prepared_tasks])
            )
        )
    }
    for result in per_task_results:
        if result.persisted and result.structured is not None:
            task = tasks_by_id.get(result.task_id)
            if task is not None:
                task.task_description_structured = result.structured
    session.flush()
    return _aggregate(
        analysis_id=analysis_id,
        rule_set_id=rule_set_id,
        prompt_profile_id=prompt_profile_id,
        per_task=per_task_results,
    )


def _structure_task(
    *,
    task: _PreparedTask,
    prompt_template: str,
    model_alias: str,
    temperature: float,
    max_tokens: int,
    llm_client: LiteLLMClientProtocol,
) -> TaskStructuringTaskResult:
    description = task.description
    if not description.strip():
        # Empty descriptions can't produce useful structure — skip silently
        # rather than waste an LLM call. The empty `{}` stays in place.
        return TaskStructuringTaskResult(task_id=task.task_id)

    payload = {
        "task_code": task.task_code,
        "task_name": task.task_name,
        "task_description": description[:_MAX_DESCRIPTION_CHARS_FOR_PROMPT],
    }
    messages = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        content, _summary = llm_client.call(
            model_alias,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except LiteLLMCallError as exc:
        logger.warning(
            "task_structuring LLM call failed for task=%s: %s", task.task_id, exc,
        )
        return TaskStructuringTaskResult(
            task_id=task.task_id, rejected=True, rejected_reason="llm_call_failed",
        )

    structured = _parse_buckets(content)
    if structured is None:
        return TaskStructuringTaskResult(
            task_id=task.task_id, rejected=True,
            rejected_reason=RejectReason.SCHEMA_INVALID,
        )

    reject_reason = _evaluate_guardrails(structured)
    if reject_reason:
        return TaskStructuringTaskResult(
            task_id=task.task_id, rejected=True, rejected_reason=reject_reason,
        )

    return TaskStructuringTaskResult(
        task_id=task.task_id, persisted=True, structured=structured
    )


def _parse_buckets(content: str) -> dict[str, list[str]] | None:
    """Parse the LLM response into a clean 4-bucket dict.

    Accepts either `{target_roles: [...], ...}` or the same wrapped in
    `{"items": {...}}`. Returns None when the response isn't valid JSON,
    when any of the 4 required keys is missing, or when a bucket value
    isn't a list of strings.
    """
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict) and "items" in parsed and isinstance(parsed["items"], dict):
        parsed = parsed["items"]
    if not isinstance(parsed, dict):
        return None

    cleaned: dict[str, list[str]] = {}
    for bucket in _BUCKETS:
        value = parsed.get(bucket)
        if not isinstance(value, list):
            return None
        bucket_items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            stripped = item.strip()
            if not stripped:
                continue
            bucket_items.append(stripped)
        cleaned[bucket] = bucket_items
    return cleaned


def _evaluate_guardrails(structured: dict[str, list[str]]) -> str | None:
    """Hard guardrails listed in the rule_set's `guardrails` token list.

    Returns the first reject reason, or None when the structured object
    passes all checks.
    """
    # reject_empty_all_buckets: if every bucket is empty, the LLM produced
    # nothing useful — better to drop than to overwrite the empty `{}` with
    # another empty object (silent no-op).
    if all(not structured[b] for b in _BUCKETS):
        return RejectReason.GUARDRAIL_EMPTY_ALL_BUCKETS

    # reject_string_over_64_chars: per-string length cap from the rule's
    # output_item_schema.
    for bucket in _BUCKETS:
        for item in structured[bucket]:
            if len(item) > _MAX_STRING_CHARS:
                return RejectReason.GUARDRAIL_STRING_OVER_64_CHARS
    return None


def _aggregate(
    *,
    analysis_id: str,
    rule_set_id: str,
    prompt_profile_id: str,
    per_task: list[TaskStructuringTaskResult],
) -> TaskStructuringResult:
    structured = sum(1 for r in per_task if r.persisted)
    rejected = sum(1 for r in per_task if r.rejected)
    quality: dict[str, int] = {}
    for r in per_task:
        if r.rejected and r.rejected_reason:
            key = f"task_structuring_{r.rejected_reason}"
            quality[key] = quality.get(key, 0) + 1
    if structured:
        quality["task_structuring_tasks_structured"] = structured
    return TaskStructuringResult(
        analysis_id=analysis_id,
        rule_set_id=rule_set_id,
        prompt_profile_id=prompt_profile_id,
        tasks_processed=len(per_task),
        tasks_structured=structured,
        tasks_rejected=rejected,
        quality_summary=quality,
    )


def _load_active_rule_set(session: Session) -> models.AIAnalysisRules | None:
    return session.scalars(
        select(models.AIAnalysisRules).where(
            models.AIAnalysisRules.scenario == SCENARIO,
            models.AIAnalysisRules.is_active.is_(True),
        ).order_by(models.AIAnalysisRules.version.desc())
    ).first()


def _load_active_prompt_profile(session: Session) -> models.AIPromptProfile | None:
    return session.scalars(
        select(models.AIPromptProfile).where(
            models.AIPromptProfile.scenario == SCENARIO,
            models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
        ).order_by(models.AIPromptProfile.profile_version.desc())
    ).first()


def _skipped(
    analysis: models.OccupationalAbilityAnalysis, reason: str
) -> TaskStructuringResult:
    return TaskStructuringResult(
        analysis_id=analysis.id,
        rule_set_id="",
        prompt_profile_id="",
        skipped=True,
        skipped_reason=reason,
    )


__all__ = [
    "SCENARIO",
    "RejectReason",
    "TaskStructuringResult",
    "TaskStructuringTaskResult",
    "structure_task_descriptions_for_analysis",
]
