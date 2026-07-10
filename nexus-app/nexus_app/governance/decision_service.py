"""GovernanceDecisionService — generates governance_result from AI run + governance_rules.json.

Decision rule: confidence >= confidence_threshold_auto_adopt
AND quality_level == pass AND level not requiring approval
-> status = available; otherwise review_required with reason.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.rules_config import GovernanceRulesConfig
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.audit import write_audit
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AuditEventType,
    GovernanceResultStatus,
)
from nexus_app.governance.schemas import AdoptionStatus, DecisionTrailEntry

logger = logging.getLogger(__name__)

_TAG_DIMENSION_KEYS = frozenset({
    "professional_domain",
    "education_level",
    "geographic_scope",
    "timeliness",
    "data_source_type",
})
_NON_BUSINESS_TAG_VALUES = frozenset({
    "file_upload",
    "文件上传",
    "本地文件上传",
    "nas",
    "crawler",
    "爬虫",
    "database",
    "数据库",
    "webhook",
    "api推送",
    "API推送",
    "第三方API推送",
})


def _is_valid_tag_value(value: str) -> bool:
    if value.startswith("#") or value.startswith("_"):
        return False
    if value in _NON_BUSINESS_TAG_VALUES:
        return False
    return not re.search(r"(?:gpt|doubao|qwen|deepseek|claude|gemini)[-_a-z0-9.]*", value, re.I)


def _extract_governance_tags(ai_output: dict[str, Any]) -> list[str]:
    """Backwards-compatible flat-list projection of ``ai_output.tags``.

    v1.3 §4.1 tagging profile v2 emits a **structured 7-category dict**,
    while pre-v1.3 tagging profile v1 emitted a flat list (or a 5-dimension
    dict later flattened here).  This function collapses either shape into
    the same ``list[str]`` currently expected by ``GovernanceResult.tags``
    (see the ``list[str]`` column type declared in
    ``nexus_app.models.GovernanceResult``).

    Structured payloads are also stored **verbatim** in
    ``AIGovernanceRun.ai_output.tags`` so downstream consumers that read
    the run rather than the derived result can reconstruct the full 7-bucket
    view via :func:`nexus_app.ai_governance.tag_payload.normalize_to_structured`.
    """
    tags: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, dict):
            value = value.get("value") or value.get("code") or value.get("tag")
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned and _is_valid_tag_value(cleaned) and cleaned not in seen:
                seen.add(cleaned)
                tags.append(cleaned)

    def add_many(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                add_many(item)
        elif isinstance(value, dict):
            if any(key in value for key in ("value", "code", "tag")):
                add(value)
            else:
                for nested in value.values():
                    add_many(nested)
        else:
            add(value)

    # v1.3 structured-shape fast path: if the tagging payload is already a
    # StructuredTagBag-shaped dict, delegate flattening to the canonical
    # ``flatten_to_legacy`` helper.  This keeps the ordering and dedup
    # semantics of the structured-tag world consistent with the legacy
    # world without duplicating the traversal rules here.
    tagging_payload = ai_output.get("tags")
    if _looks_structured_tag_bag(tagging_payload):
        from nexus_app.ai_governance.tag_payload import (
            STRUCTURED_TAG_CATEGORY_CODES,
            flatten_to_legacy,
        )

        # ``flatten_to_legacy`` already de-duplicates and preserves canonical
        # bucket order.  We still run the flat output through the
        # ``_is_valid_tag_value`` filter to stay consistent with the legacy
        # cleanup rules (drops model-alias-shaped strings, "_"-prefixed
        # sentinels, etc.).
        _ = STRUCTURED_TAG_CATEGORY_CODES  # keep import cost accounted for
        for value in flatten_to_legacy(tagging_payload):
            add(value)
    else:
        add_many(tagging_payload)

    # _stages.tagging follows the same shape as the top-level tags; support
    # both structured and legacy payloads here too.
    stages = ai_output.get("_stages")
    tagging_stage = stages.get("tagging") if isinstance(stages, dict) else None
    if isinstance(tagging_stage, dict):
        stage_payload = tagging_stage.get("tags")
        if _looks_structured_tag_bag(stage_payload):
            from nexus_app.ai_governance.tag_payload import flatten_to_legacy

            for value in flatten_to_legacy(stage_payload):
                add(value)
        else:
            add_many(stage_payload)
    for dim_key in _TAG_DIMENSION_KEYS:
        if dim_key in ai_output:
            add_many(ai_output[dim_key])
    return tags


def _looks_structured_tag_bag(payload: Any) -> bool:
    """Return True when the payload uses v1.3 §4.1 structured shape.

    A structured tag bag is a dict with **at least one** of the seven
    canonical bucket names (regions / industries / occupations / majors /
    abilities / topics / time_ranges).  Legacy 5-dimension outputs
    (professional_domain / geographic_scope / …) intentionally do **not**
    match — they go through the recursive ``add_many`` path so their
    per-dimension keys are handled uniformly.
    """
    if not isinstance(payload, dict):
        return False
    from nexus_app.ai_governance.tag_payload import STRUCTURED_TAG_CATEGORY_CODES

    return any(key in payload for key in STRUCTURED_TAG_CATEGORY_CODES)


class GovernanceDecisionError(Exception):
    pass


class GovernanceDecisionService:
    """Reads AI governance run output + governance_rules.json thresholds,
    produces a persisted governance_result with full decision_trail."""

    def __init__(self, registry: GovernanceRulesRegistry) -> None:
        self._registry = registry

    def execute_governance(
        self,
        session: Session,
        ai_run: models.AIGovernanceRun,
        *,
        user_id: str | None = None,
    ) -> models.GovernanceResult:
        """Generate governance_result from a completed AI governance run."""
        if ai_run.ai_output is None:
            raise GovernanceDecisionError(
                f"AI run {ai_run.id} has no ai_output; cannot produce decision"
            )

        # Idempotency: return existing result if this (normalized_ref_id, ai_run_id)
        # has already been processed (e.g. job retry after a transient failure).
        existing = session.scalars(
            select(models.GovernanceResult).where(
                models.GovernanceResult.normalized_ref_id == ai_run.normalized_ref_id,
                models.GovernanceResult.ai_run_id == ai_run.id,
            ).limit(1)
        ).first()
        if existing is not None:
            logger.info(
                "Idempotent: reusing GovernanceResult %s for ai_run %s",
                existing.id, ai_run.id,
            )
            return existing

        config = self._registry._ensure_loaded()
        rules_snapshot = self._take_rules_snapshot(config)
        ai_output = ai_run.ai_output
        quality_summary = ai_run.quality_summary or {}

        trail: list[DecisionTrailEntry] = []
        threshold = config.quality_scoring.confidence_threshold_auto_adopt

        trail.append(self._check_classification(ai_output, config, threshold))
        trail.append(self._check_level(ai_output, config, threshold))
        trail.append(self._check_tags(ai_output, config, threshold))
        trail.append(self._check_quality(quality_summary, config))

        overall_status = self._determine_overall_status(trail)
        index_admission = overall_status == GovernanceResultStatus.AVAILABLE

        trace_id = str(uuid.uuid4())
        result = models.GovernanceResult(
            normalized_ref_id=ai_run.normalized_ref_id,
            ai_run_id=ai_run.id,
            classification=ai_output.get("classification"),
            level=ai_output.get("level"),
            tags=_extract_governance_tags(ai_output),
            org_scope=ai_output.get("org_scope"),
            index_admission=index_admission,
            quality_summary=quality_summary,
            decision_trail=[e.model_dump() for e in trail],
            rules_schema_version=rules_snapshot["schema_version"],
            rules_content_hash=rules_snapshot["content_hash"],
            rules_version_id=rules_snapshot.get("rules_version_id"),
            status=overall_status,
            created_by=user_id,
            trace_id=trace_id,
        )
        session.add(result)

        # Move the AI run out of pending_rule_guardrail now that the decision
        # service has produced a result. Without this the workbench "待人工复核"
        # filter — which keys on `run.adoption_status === pending_rule_guardrail`
        # — would keep showing every historical run forever.
        ai_run.adoption_status = self._derive_run_adoption_status(trail, overall_status)
        session.flush()

        write_audit(
            session,
            AuditEventType.GOVERNANCE_RESULT_CREATED,
            target_type="governance_result",
            target_id=result.id,
            trace_id=trace_id,
            summary={
                "normalized_ref_id": ai_run.normalized_ref_id,
                "ai_run_id": ai_run.id,
                "status": overall_status.value,
                "ai_run_adoption_status": ai_run.adoption_status.value,
                "rules_schema_version": rules_snapshot["schema_version"],
            },
            actor_id=user_id,
        )
        return result

    @staticmethod
    def _derive_run_adoption_status(
        trail: list[DecisionTrailEntry],
        overall_status: GovernanceResultStatus,
    ) -> AIGovernanceRunAdoptionStatus:
        """Project the decision trail onto the AI run adoption enum.

        - Any entry rejected → run rejected.
        - Otherwise any review_required entry (or overall review_required) → review_required.
        - Otherwise → auto_adopted.
        """
        if any(e.adoption_status == "rejected" for e in trail):
            return AIGovernanceRunAdoptionStatus.REJECTED
        if overall_status == GovernanceResultStatus.REVIEW_REQUIRED:
            return AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED
        return AIGovernanceRunAdoptionStatus.AUTO_ADOPTED

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _take_rules_snapshot(self, config: GovernanceRulesConfig) -> dict[str, str]:
        content_hash = self._registry.get_rules_content_hash()
        return {
            "schema_version": config.schema_version,
            "content_hash": content_hash,
            "rules_version_id": self._registry.get_rules_version_id(),
        }

    def _check_classification(
        self, ai_output: dict[str, Any], config: GovernanceRulesConfig, threshold: float
    ) -> DecisionTrailEntry:
        confidence = float(ai_output.get("confidence", 0))
        suggestion = ai_output.get("classification", "")
        valid_codes = {c.code for c in config.classifications}

        checks: dict[str, Any] = {
            "confidence_threshold_auto_adopt": threshold,
            "actual_confidence": confidence,
            "valid_classifications": sorted(valid_codes),
        }

        if confidence < threshold:
            return DecisionTrailEntry(
                field_name="classification",
                ai_suggestion=suggestion,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=suggestion,
                adoption_status="review_required",
                review_reason=f"confidence {confidence:.2f} < threshold {threshold}",
            )

        if suggestion not in valid_codes:
            return DecisionTrailEntry(
                field_name="classification",
                ai_suggestion=suggestion,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=suggestion,
                adoption_status="rejected",
                review_reason=f"classification '{suggestion}' not in valid set",
            )

        return DecisionTrailEntry(
            field_name="classification",
            ai_suggestion=suggestion,
            ai_confidence=confidence,
            threshold_check=checks,
            final_value=suggestion,
            adoption_status="auto_adopted",
        )

    def _check_level(
        self, ai_output: dict[str, Any], config: GovernanceRulesConfig, threshold: float
    ) -> DecisionTrailEntry:
        confidence = float(ai_output.get("confidence", 0))
        suggestion = ai_output.get("level", "L1")
        level_def = next((lv for lv in config.levels if lv.code == suggestion), None)
        requires_approval = level_def.requires_approval if level_def else False

        checks: dict[str, Any] = {
            "confidence_threshold_auto_adopt": threshold,
            "actual_confidence": confidence,
            "requires_approval": requires_approval,
        }

        if confidence < threshold:
            return DecisionTrailEntry(
                field_name="level",
                ai_suggestion=suggestion,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=suggestion,
                adoption_status="review_required",
                review_reason=f"confidence {confidence:.2f} < threshold {threshold}",
            )

        if requires_approval:
            return DecisionTrailEntry(
                field_name="level",
                ai_suggestion=suggestion,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=suggestion,
                adoption_status="review_required",
                review_reason=f"level {suggestion} requires_approval=true",
            )

        return DecisionTrailEntry(
            field_name="level",
            ai_suggestion=suggestion,
            ai_confidence=confidence,
            threshold_check=checks,
            final_value=suggestion,
            adoption_status="auto_adopted",
        )

    def _check_tags(
        self, ai_output: dict[str, Any], config: GovernanceRulesConfig, threshold: float
    ) -> DecisionTrailEntry:
        confidence = float(ai_output.get("confidence", 0))
        suggestion = _extract_governance_tags(ai_output)

        checks: dict[str, Any] = {
            "confidence_threshold_auto_adopt": threshold,
            "actual_confidence": confidence,
            "tag_contract": "free_form_values_under_fixed_dimensions",
            "extracted_tag_count": len(suggestion),
        }

        if confidence < threshold:
            return DecisionTrailEntry(
                field_name="tags",
                ai_suggestion=suggestion,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=suggestion,
                adoption_status="review_required",
                review_reason=f"confidence {confidence:.2f} < threshold {threshold}",
            )

        return DecisionTrailEntry(
            field_name="tags",
            ai_suggestion=suggestion,
            ai_confidence=confidence,
            threshold_check=checks,
            final_value=suggestion,
            adoption_status="auto_adopted",
        )

    def _check_quality(
        self, quality_summary: dict[str, Any], config: GovernanceRulesConfig
    ) -> DecisionTrailEntry:
        score = float(quality_summary.get("quality_score", 0))
        quality_level = quality_summary.get("quality_level", "fail")
        confidence = float(quality_summary.get("confidence", 0))
        blocking_reasons = quality_summary.get("blocking_reasons") or []
        thresholds = config.quality_scoring.thresholds

        checks: dict[str, Any] = {
            "pass_threshold": thresholds.pass_,
            "warning_threshold": thresholds.warning,
            "review_required_below": thresholds.review_required_below,
            "actual_score": score,
            "actual_level": quality_level,
            "blocking_reasons": list(blocking_reasons),
        }

        # Any blocking check (severity=blocking, status=fail) forces review_required
        # regardless of quality_level / score — otherwise warning-level results can
        # slip through with non-empty blocking_reasons and end up "available", which
        # is the state inconsistency we hit on ref 31df3090...84bd.
        if blocking_reasons:
            return DecisionTrailEntry(
                field_name="quality",
                ai_suggestion=score,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=score,
                adoption_status="review_required",
                review_reason=(
                    "blocking quality checks failed: "
                    + "; ".join(str(r) for r in blocking_reasons)
                ),
            )

        if quality_level == "fail":
            return DecisionTrailEntry(
                field_name="quality",
                ai_suggestion=score,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=score,
                adoption_status="review_required",
                review_reason=f"quality_level=fail (score {score} < pass {thresholds.pass_})",
            )

        if thresholds.review_required_below > 0 and score < thresholds.review_required_below:
            return DecisionTrailEntry(
                field_name="quality",
                ai_suggestion=score,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=score,
                adoption_status="review_required",
                review_reason=f"score {score} < review_required_below {thresholds.review_required_below}",
            )

        return DecisionTrailEntry(
            field_name="quality",
            ai_suggestion=score,
            ai_confidence=confidence,
            threshold_check=checks,
            final_value=score,
            adoption_status="auto_adopted",
        )

    @staticmethod
    def _determine_overall_status(
        trail: list[DecisionTrailEntry],
    ) -> GovernanceResultStatus:
        for entry in trail:
            if entry.adoption_status in ("review_required", "rejected"):
                return GovernanceResultStatus.REVIEW_REQUIRED
        return GovernanceResultStatus.AVAILABLE
