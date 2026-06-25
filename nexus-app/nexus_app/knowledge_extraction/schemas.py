"""Schemas for the knowledge-unit extraction service.

Kept separate from `rules_loader.py` so test harnesses can import the result
dataclasses without dragging the SQLAlchemy / JSON loader chain along.

Contract source: `docs/pipeline_b_contract_freeze.md §5.3 / §八` +
`config/ai_analysis_rules.json::occupation.job_demand.requirement_extraction.rules`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


# `item_type` whitelist mirrors the JSON-schema enum on the rule_set's
# `output_item_schema`. Duplicated here as a Python-side authority so the
# guardrail evaluator + writer don't have to re-parse the schema on every
# request.
ALLOWED_ITEM_TYPES: frozenset[str] = frozenset({
    "professional_skill",
    "tool",
    "certificate",
    "professional_literacy",
    "work_task_candidate",
})


# Reasons the service drops a candidate item. Stable strings so the dataset's
# `quality_summary.extraction_*` counters partition predictably.
class RejectReason:
    SCHEMA_INVALID = "schema_invalid"
    GUARDRAIL_LITERACY_MIXED = "guardrail_literacy_mixed_with_skill"
    GUARDRAIL_ITEM_NAME_TOO_LONG = "guardrail_skill_name_over_128_chars"
    GUARDRAIL_CERT_NEEDS_QUALIFIER = "guardrail_certificate_without_acronym_or_full_name"
    GUARDRAIL_EMPTY_ITEM_NAME = "guardrail_empty_item_name"
    GUARDRAIL_UNKNOWN_TYPE = "guardrail_unknown_item_type"


@dataclass(frozen=True)
class ExtractedItem:
    """One LLM-extracted candidate item.

    Mirrors `job_demand_requirement_item` columns + auto_admit decision.
    `is_low_confidence` is True when confidence is below the rule_set's
    `auto_admit_threshold` — the item is still persisted (so reviewers can
    triage) but counted separately on the dataset's quality summary.
    """
    item_type: str
    item_name: str
    raw_text: str | None
    normalized_name: str | None
    taxonomy_code: str | None
    evidence_field: str | None
    confidence: Decimal
    is_low_confidence: bool


@dataclass(frozen=True)
class ExtractionRecordResult:
    """Per-record summary returned by the service for one job_demand_record."""
    record_id: str
    items_persisted: int = 0
    items_low_confidence: int = 0
    items_rejected: int = 0
    reject_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionDatasetResult:
    """Dataset-level summary returned by the service.

    Counts roll up from the per-record runs. `quality_summary` follows the
    same key convention writers use elsewhere (snake_case, prefixed with the
    domain so it doesn't collide with B4's `placeholder_row_dropped` /
    `duplicate_fingerprint`).
    """
    dataset_id: str
    rule_set_id: str
    prompt_profile_id: str
    records_processed: int = 0
    items_persisted: int = 0
    items_low_confidence: int = 0
    items_rejected: int = 0
    quality_summary: dict[str, int] = field(default_factory=dict)
    skipped: bool = False
    skipped_reason: str | None = None


__all__ = [
    "ALLOWED_ITEM_TYPES",
    "RejectReason",
    "ExtractedItem",
    "ExtractionRecordResult",
    "ExtractionDatasetResult",
]
