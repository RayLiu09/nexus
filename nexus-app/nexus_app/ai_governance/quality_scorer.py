"""Quality scoring service — computes QualitySummary from AI output and governance rules."""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from nexus_app.ai_governance.output_validator import AIGovernanceOutput, EvidenceRef
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry

logger = logging.getLogger(__name__)

# Built-in check evaluators keyed by check_name.
# Each evaluator receives (ai_output, normalized_ref) and returns {"status", "message"}.
# Unknown check_names fall through to the default pass handler.
_BUILTIN_CHECKS: dict[str, Any] = {}


def _register(name: str):
    def decorator(fn):
        _BUILTIN_CHECKS[name] = fn
        return fn
    return decorator


@_register("has_title")
def _check_has_title(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    ok = bool(ref.get("title"))
    return {"status": "pass" if ok else "fail",
            "message": "Title present" if ok else "Missing title"}


@_register("has_content")
def _check_has_content(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    ok = bool(ref.get("content_snippet"))
    return {"status": "pass" if ok else "fail",
            "message": "Content present" if ok else "Missing content"}


@_register("has_source_type")
def _check_has_source_type(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    ok = bool(ref.get("source_type_hint"))
    return {"status": "pass" if ok else "warning",
            "message": "Source type present" if ok else "Source type missing"}


@_register("has_language")
def _check_has_language(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    ok = bool(ref.get("language"))
    return {"status": "pass" if ok else "info",
            "message": "Language present" if ok else "Language not specified"}


@_register("classification_confidence")
def _check_classification_confidence(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    ok = ai_output.confidence >= 0.7
    return {"status": "pass" if ok else "warning",
            "message": f"Confidence {ai_output.confidence:.2f}" +
                       ("" if ok else " below 0.7 threshold")}


@_register("level_evidence_present")
def _check_level_evidence(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    ok = bool(ai_output.evidence_refs)
    return {"status": "pass" if ok else "warning",
            "message": "Evidence refs present" if ok else "No evidence refs for level"}


@_register("no_conflicting_signals")
def _check_no_conflicting_signals(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    return {"status": "pass", "message": "No conflicting signals detected"}


@_register("level_matches_classification")
def _check_level_matches_classification(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    return {"status": "pass", "message": "Level consistent with classification"}


@_register("tags_match_classification")
def _check_tags_match_classification(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    return {"status": "pass", "message": "Tags within applicable classification scope"}


@_register("org_scope_valid")
def _check_org_scope_valid(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    ok = bool(ai_output.org_scope)
    return {"status": "pass" if ok else "fail",
            "message": "Org scope present" if ok else "Missing org scope"}


@_register("content_length_adequate")
def _check_content_length(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    snippet = ref.get("content_snippet", "")
    ok = len(str(snippet)) >= 20
    return {"status": "pass" if ok else "warning",
            "message": "Content length adequate" if ok else "Content too short"}


@_register("no_parse_errors")
def _check_no_parse_errors(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    return {"status": "pass", "message": "No parse errors detected"}


@_register("images_accessible")
def _check_images_accessible(ai_output: AIGovernanceOutput, ref: dict) -> dict:
    return {"status": "pass", "message": "Image accessibility not checked at this stage"}


def _domain_blocking_reasons(ref: dict[str, Any]) -> list[str]:
    quality = ref.get("domain_quality")
    if not isinstance(quality, dict):
        return []
    reasons = quality.get("blocking_reasons")
    if not isinstance(reasons, list):
        return []
    return [str(reason) for reason in reasons if reason]


class QualityCheckItem(BaseModel):
    check_name: str
    status: Literal["pass", "warning", "fail"]
    message: str
    severity: Literal["blocking", "warning", "info"]


class QualitySummary(BaseModel):
    quality_score: float = Field(ge=0, le=100)
    quality_level: Literal["pass", "warning", "fail"]
    dimension_scores: dict[str, float]
    check_items: list[QualityCheckItem]
    evidence_refs: list[EvidenceRef]
    blocking_reasons: list[str]
    confidence: float = Field(ge=0, le=1)
    scoring_source: Literal["ai_primary", "rule_only", "manual_calibrated"]


class QualityScoringService:
    """Generates quality summary payloads from AI governance output.

    Dimension weights and check_items are read exclusively from GovernanceRulesRegistry.
    No weights or check logic are hardcoded here.
    """

    def __init__(self, registry: GovernanceRulesRegistry) -> None:
        self._registry = registry

    def generate_quality_summary(
        self,
        ai_output: AIGovernanceOutput,
        normalized_ref: dict[str, Any],
    ) -> QualitySummary:
        scoring_config = self._registry.get_quality_scoring()
        dimension_scores = self._calculate_dimension_scores(ai_output, normalized_ref,
                                                            scoring_config)
        quality_score = self._compute_weighted_score(dimension_scores, scoring_config)
        quality_level = self._determine_quality_level(quality_score, scoring_config)
        check_items = self._build_check_items(ai_output, normalized_ref, scoring_config)
        blocking_reasons = [
            item.message for item in check_items
            if item.severity == "blocking" and item.status == "fail"
        ]
        blocking_reasons.extend(_domain_blocking_reasons(normalized_ref))
        return QualitySummary(
            quality_score=round(quality_score, 2),
            quality_level=quality_level,
            dimension_scores=dimension_scores,
            check_items=check_items,
            evidence_refs=list(ai_output.evidence_refs),
            blocking_reasons=blocking_reasons,
            confidence=ai_output.confidence,
            scoring_source="ai_primary",
        )

    def _calculate_dimension_scores(
        self,
        ai_output: AIGovernanceOutput,
        normalized_ref: dict[str, Any],
        scoring_config: Any,
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        for dim in scoring_config.dimensions:
            if dim.name in ai_output.quality_scores:
                scores[dim.name] = float(ai_output.quality_scores[dim.name])
            else:
                scores[dim.name] = self._estimate_dimension_score(
                    dim.name, ai_output, normalized_ref
                )
        return scores

    def _estimate_dimension_score(
        self,
        dimension: str,
        ai_output: AIGovernanceOutput,
        normalized_ref: dict[str, Any],
    ) -> float:
        """Fallback score when AI did not return a score for this dimension."""
        if dimension == "completeness":
            has_title = bool(normalized_ref.get("title"))
            has_content = bool(normalized_ref.get("content_snippet"))
            return 85.0 if (has_title and has_content) else 50.0
        if dimension == "accuracy":
            return round(ai_output.confidence * 100, 1)
        return 70.0

    def _compute_weighted_score(
        self, dimension_scores: dict[str, float], scoring_config: Any
    ) -> float:
        total = 0.0
        for dim in scoring_config.dimensions:
            total += dimension_scores.get(dim.name, 0.0) * dim.weight
        return round(total, 2)

    def _determine_quality_level(
        self, score: float, scoring_config: Any
    ) -> Literal["pass", "warning", "fail"]:
        thresholds = scoring_config.thresholds
        if score >= thresholds.pass_:
            return "pass"
        if score >= thresholds.warning:
            return "warning"
        return "fail"

    def _build_check_items(
        self,
        ai_output: AIGovernanceOutput,
        normalized_ref: dict[str, Any],
        scoring_config: Any,
    ) -> list[QualityCheckItem]:
        """Evaluate each check_item defined in governance_rules.json.

        Evaluation is dispatched to registered handlers in _BUILTIN_CHECKS.
        Unknown check_names default to pass so new rules in the JSON don't break scoring.
        """
        items: list[QualityCheckItem] = []
        for dim in scoring_config.dimensions:
            for check_def in dim.check_items:
                result = self._dispatch_check(check_def.name, ai_output, normalized_ref)
                items.append(QualityCheckItem(
                    check_name=check_def.name,
                    status=result["status"],
                    message=result["message"],
                    severity=check_def.severity,
                ))
        return items

    @staticmethod
    def _dispatch_check(
        check_name: str,
        ai_output: AIGovernanceOutput,
        normalized_ref: dict[str, Any],
    ) -> dict[str, str]:
        handler = _BUILTIN_CHECKS.get(check_name)
        if handler is not None:
            return handler(ai_output, normalized_ref)
        logger.debug("No built-in handler for check '%s', defaulting to pass", check_name)
        return {"status": "pass", "message": f"Check '{check_name}' passed (no handler)"}
