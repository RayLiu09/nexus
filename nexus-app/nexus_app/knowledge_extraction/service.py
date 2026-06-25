"""LLM-driven extraction of job_demand requirement items.

Orchestrates: load rule_set + prompt → for each record, build prompt → call
LiteLLM → parse JSON → schema-validate → guardrail-evaluate → persist
accepted items into `job_demand_requirement_item`.

Trigger: invoked from `worker/runner.py:_run_domain_normalize` after the B4
writer successfully persists a `job_demand_dataset`. Skipped quietly when
the rule_set / prompt profile is missing (deployment not yet seeded), or
when LiteLLM is unavailable (returns a skipped result, not an exception).

Contract:
- `docs/pipeline_b_contract_freeze.md §5.3` (table) + §八 (rule_set) + §九
  (prompt profile)
- `nexus_app/domain_normalize/job_demand_writer.py` (upstream — owns the
  dataset row and never touches requirement_item)
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.enums import PromptProfileStatus
from nexus_app.knowledge_extraction import guardrails
from nexus_app.knowledge_extraction.schemas import (
    ALLOWED_ITEM_TYPES,
    ExtractedItem,
    ExtractionDatasetResult,
    ExtractionRecordResult,
    RejectReason,
)

logger = logging.getLogger(__name__)

# Scenario the B5.2 service binds to. Other scenarios (task_description,
# body_markdown) ship in B5.3 / B5.4 and bind to their own scenario keys.
SCENARIO: str = "job_demand_requirement_extraction"

# Hard caps so a single malformed LLM reply can't OOM the writer. The rule
# set is allowed to produce more items per record than B5.2 ultimately
# persists; anything beyond the cap counts as rejected so quality summaries
# stay honest.
_MAX_ITEMS_PER_RECORD = 50


def extract_requirements_for_dataset(
    session: Session,
    dataset: models.JobDemandDataset,
    *,
    llm_client: LiteLLMClientProtocol | None,
) -> ExtractionDatasetResult:
    """Run LLM extraction for every record in `dataset`.

    Caller owns commit. The service flushes to materialize FK targets but
    does not commit so the surrounding worker transaction stays atomic.
    """
    if llm_client is None:
        return _skipped(dataset, reason="llm_client_unavailable")

    rule_set = _load_active_rule_set(session)
    if rule_set is None:
        return _skipped(dataset, reason="rule_set_not_seeded")
    prompt = _load_active_prompt_profile(session)
    if prompt is None:
        return _skipped(dataset, reason="prompt_profile_not_seeded")

    records = list(
        session.scalars(
            select(models.JobDemandRecord).where(
                models.JobDemandRecord.dataset_id == dataset.id
            )
        )
    )
    if not records:
        # Empty dataset is not an error — the writer just had nothing to
        # write. We still emit a result so the audit shows the extraction
        # stage ran (rather than silently producing no audit at all).
        return ExtractionDatasetResult(
            dataset_id=dataset.id,
            rule_set_id=rule_set.id,
            prompt_profile_id=prompt.id,
            records_processed=0,
        )

    threshold = Decimal(str(rule_set.auto_admit_threshold))
    guardrail_tokens = list(rule_set.guardrails or [])
    field_whitelist = list(rule_set.field_whitelist or [])

    per_record_results: list[ExtractionRecordResult] = []
    for record in records:
        per_record_results.append(
            _extract_for_record(
                session,
                record=record,
                dataset_id=dataset.id,
                prompt=prompt,
                rule_set=rule_set,
                threshold=threshold,
                guardrail_tokens=guardrail_tokens,
                field_whitelist=field_whitelist,
                llm_client=llm_client,
            )
        )
    session.flush()

    return _aggregate(
        dataset_id=dataset.id,
        rule_set_id=rule_set.id,
        prompt_profile_id=prompt.id,
        per_record=per_record_results,
    )


def _extract_for_record(
    session: Session,
    *,
    record: models.JobDemandRecord,
    dataset_id: str,
    prompt: models.AIPromptProfile,
    rule_set: models.AIAnalysisRules,
    threshold: Decimal,
    guardrail_tokens: list[str],
    field_whitelist: list[str],
    llm_client: LiteLLMClientProtocol,
) -> ExtractionRecordResult:
    payload = _build_llm_input(record, field_whitelist)
    messages = [
        {"role": "system", "content": prompt.prompt_template},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    response_format = {"type": "json_object"} if rule_set.output_format == "json" else None

    try:
        content, _summary = llm_client.call(
            prompt.litellm_model_alias,
            messages,
            temperature=float(prompt.temperature),
            max_tokens=int(prompt.max_input_tokens),
            response_format=response_format,
        )
    except LiteLLMCallError as exc:
        logger.warning(
            "knowledge_extraction LLM call failed for record=%s: %s",
            record.id, exc,
        )
        return ExtractionRecordResult(
            record_id=record.id,
            reject_counts={"llm_call_failed": 1},
        )

    items_raw = _parse_items(content)
    if items_raw is None:
        return ExtractionRecordResult(
            record_id=record.id,
            items_rejected=1,
            reject_counts={RejectReason.SCHEMA_INVALID: 1},
        )
    if len(items_raw) > _MAX_ITEMS_PER_RECORD:
        items_raw = items_raw[:_MAX_ITEMS_PER_RECORD]

    persisted = 0
    low_conf = 0
    rejected = 0
    reject_counts: dict[str, int] = {}

    for raw_item in items_raw:
        if not isinstance(raw_item, dict):
            rejected += 1
            reject_counts[RejectReason.SCHEMA_INVALID] = (
                reject_counts.get(RejectReason.SCHEMA_INVALID, 0) + 1
            )
            continue
        reject_reason = guardrails.evaluate(raw_item, guardrail_tokens)
        if reject_reason:
            rejected += 1
            reject_counts[reject_reason] = reject_counts.get(reject_reason, 0) + 1
            continue
        normalised = _normalise_item(raw_item, threshold)
        if normalised is None:
            rejected += 1
            reject_counts[RejectReason.SCHEMA_INVALID] = (
                reject_counts.get(RejectReason.SCHEMA_INVALID, 0) + 1
            )
            continue
        _persist_item(
            session,
            record=record,
            dataset_id=dataset_id,
            item=normalised,
            prompt=prompt,
            rule_set=rule_set,
        )
        persisted += 1
        if normalised.is_low_confidence:
            low_conf += 1

    return ExtractionRecordResult(
        record_id=record.id,
        items_persisted=persisted,
        items_low_confidence=low_conf,
        items_rejected=rejected,
        reject_counts=reject_counts,
    )


def _build_llm_input(
    record: models.JobDemandRecord, field_whitelist: list[str]
) -> dict[str, Any]:
    """Filter record fields against the rule_set's `field_whitelist`.

    Only whitelisted fields reach the LLM. Empty / None values are dropped
    so the prompt isn't padded with "field: null" noise.
    """
    out: dict[str, Any] = {"source_record_key": record.source_record_key}
    for field in field_whitelist:
        value = getattr(record, field, None)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        out[field] = value
    return out


def _parse_items(content: str) -> list[Any] | None:
    """Pull the `items` array out of the LLM's JSON response.

    Accepts two shapes (both are common with LiteLLM/OpenAI JSON mode):
      1. `{"items": [...]}`  — preferred
      2. `[...]`             — fallback (model dropped the wrapper)
    Returns None when the response isn't valid JSON or doesn't carry items.
    """
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list):
            return items
    return None


def _normalise_item(
    raw_item: dict[str, Any], threshold: Decimal
) -> ExtractedItem | None:
    """Coerce schema fields + decide auto-admit status. None = drop."""
    item_type = raw_item.get("item_type")
    item_name = raw_item.get("item_name")
    if not isinstance(item_type, str) or item_type not in ALLOWED_ITEM_TYPES:
        return None
    if not isinstance(item_name, str) or not item_name.strip():
        return None
    confidence_raw = raw_item.get("confidence")
    try:
        confidence = Decimal(str(confidence_raw))
    except (TypeError, ValueError, InvalidOperation):
        return None
    if not (Decimal("0") <= confidence <= Decimal("1")):
        return None
    return ExtractedItem(
        item_type=item_type,
        item_name=item_name.strip()[:128],
        raw_text=_optional_str(raw_item.get("raw_text"), max_len=512),
        normalized_name=_optional_str(raw_item.get("normalized_name"), max_len=128),
        taxonomy_code=_optional_str(raw_item.get("taxonomy_code"), max_len=64),
        evidence_field=_optional_str(raw_item.get("evidence_field"), max_len=64),
        confidence=confidence,
        is_low_confidence=confidence < threshold,
    )


def _optional_str(value: Any, *, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:max_len]


def _persist_item(
    session: Session,
    *,
    record: models.JobDemandRecord,
    dataset_id: str,
    item: ExtractedItem,
    prompt: models.AIPromptProfile,
    rule_set: models.AIAnalysisRules,
) -> None:
    session.add(
        models.JobDemandRequirementItem(
            id=str(uuid4()),
            record_id=record.id,
            dataset_id=dataset_id,
            item_type=item.item_type,
            item_name=item.item_name,
            raw_text=item.raw_text,
            normalized_name=item.normalized_name,
            taxonomy_code=item.taxonomy_code,
            confidence=item.confidence,
            extractor_version=prompt.prompt_version,
            evidence_field=item.evidence_field,
            prompt_template_id=prompt.id,
            rules_version_id=rule_set.id,
            ai_model_alias=prompt.litellm_model_alias,
        )
    )


def _aggregate(
    *,
    dataset_id: str,
    rule_set_id: str,
    prompt_profile_id: str,
    per_record: Iterable[ExtractionRecordResult],
) -> ExtractionDatasetResult:
    records_processed = 0
    items_persisted = 0
    items_low_confidence = 0
    items_rejected = 0
    quality_summary: dict[str, int] = {}

    for r in per_record:
        records_processed += 1
        items_persisted += r.items_persisted
        items_low_confidence += r.items_low_confidence
        items_rejected += r.items_rejected
        for reason, count in r.reject_counts.items():
            key = f"extraction_{reason}"
            quality_summary[key] = quality_summary.get(key, 0) + count
    if items_low_confidence:
        quality_summary["extraction_low_confidence_items"] = items_low_confidence
    if items_persisted:
        quality_summary["extraction_items_persisted"] = items_persisted

    return ExtractionDatasetResult(
        dataset_id=dataset_id,
        rule_set_id=rule_set_id,
        prompt_profile_id=prompt_profile_id,
        records_processed=records_processed,
        items_persisted=items_persisted,
        items_low_confidence=items_low_confidence,
        items_rejected=items_rejected,
        quality_summary=quality_summary,
    )


def _load_active_rule_set(session: Session) -> models.AIAnalysisRules | None:
    """Return the active rule_set for the extraction scenario, latest first.

    There should be exactly one active rule_set per scenario in P0, but we
    sort by version desc as defence-in-depth so an operator who flips an
    older row to active doesn't get the wrong one.
    """
    return session.scalars(
        select(models.AIAnalysisRules)
        .where(
            models.AIAnalysisRules.scenario == SCENARIO,
            models.AIAnalysisRules.is_active.is_(True),
        )
        .order_by(models.AIAnalysisRules.version.desc())
    ).first()


def _load_active_prompt_profile(session: Session) -> models.AIPromptProfile | None:
    """Return the active prompt profile for the extraction scenario.

    `AIPromptProfile.status == ACTIVE` is the gate; profile_version ties
    are broken by the highest version (operator-saved tunings replace the
    seed).
    """
    return session.scalars(
        select(models.AIPromptProfile)
        .where(
            models.AIPromptProfile.scenario == SCENARIO,
            models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
        )
        .order_by(models.AIPromptProfile.profile_version.desc())
    ).first()


def _skipped(
    dataset: models.JobDemandDataset, *, reason: str
) -> ExtractionDatasetResult:
    return ExtractionDatasetResult(
        dataset_id=dataset.id,
        rule_set_id="",
        prompt_profile_id="",
        skipped=True,
        skipped_reason=reason,
    )


__all__ = [
    "SCENARIO",
    "extract_requirements_for_dataset",
]
