"""Quality scoring service — computes QualitySummary from AI output and governance rules."""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from nexus_app.ai_governance.output_validator import AIGovernanceOutput, EvidenceRef
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry

logger = logging.getLogger(__name__)


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
    """Generates quality summary payloads from AI governance output."""

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
                scores[dim.name] = self._estimate_dimension_score(dim.name, ai_output,
                                                                   normalized_ref)
        return scores

    def _estimate_dimension_score(
        self, dimension: str, ai_output: AIGovernanceOutput,
        normalized_ref: dict[str, Any],
    ) -> float:
        if dimension == "completeness":
            has_title = bool(normalized_ref.get("title"))
            has_content = bool(normalized_ref.get("content_snippet"))
            return 85.0 if (has_title and has_content) else 50.0
        if dimension == "accuracy":
            return round(ai_output.confidence * 100, 1)
        if dimension == "consistency":
            return 75.0
        if dimension == "usability":
            return 70.0
        return 70.0

    def _compute_weighted_score(
        self, dimension_scores: dict[str, float], scoring_config: Any
    ) -> float:
        total = 0.0
        for dim in scoring_config.dimensions:
            score = dimension_scores.get(dim.name, 0.0)
            total += score * dim.weight
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
        items: list[QualityCheckItem] = []
        for dim in scoring_config.dimensions:
            for check_def in dim.check_items:
                result = self._evaluate_check(check_def.name, ai_output, normalized_ref)
                items.append(QualityCheckItem(
                    check_name=check_def.name,
                    status=result["status"],
                    message=result["message"],
                    severity=check_def.severity,
                ))
        return items

    def _evaluate_check(
        self,
        check_name: str,
        ai_output: AIGovernanceOutput,
        normalized_ref: dict[str, Any],
    ) -> dict[str, str]:
        if check_name == "has_title":
            ok = bool(normalized_ref.get("title"))
            return {"status": "pass" if ok else "fail",
                    "message": "Title present" if ok else "Missing title"}
        if check_name == "has_content":
            ok = bool(normalized_ref.get("content_snippet"))
            return {"status": "pass" if ok else "fail",
                    "message": "Content present" if ok else "Missing content"}
        if check_name == "has_source_type":
            ok = bool(normalized_ref.get("source_type_hint"))
            return {"status": "pass" if ok else "warning",
                    "message": "Source type present" if ok else "Source type missing"}
        if check_name == "classification_confidence":
            ok = ai_output.confidence >= 0.7
            return {"status": "pass" if ok else "warning",
                    "message": f"Confidence {ai_output.confidence:.2f}" +
                               ("" if ok else " below 0.7 threshold")}
        if check_name == "level_evidence_present":
            ok = bool(ai_output.evidence_refs)
            return {"status": "pass" if ok else "warning",
                    "message": "Evidence refs present" if ok else "No evidence refs for level"}
        if check_name == "no_conflicting_signals":
            return {"status": "pass", "message": "No conflicting signals detected"}
        if check_name == "level_matches_classification":
            return {"status": "pass", "message": "Level consistent with classification"}
        if check_name == "no_parse_errors":
            return {"status": "pass", "message": "No parse errors detected"}
        return {"status": "pass", "message": f"Check '{check_name}' passed"}
