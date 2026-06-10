"""GovernanceDecisionService — generates governance_result from AI run + governance_rules.json.

Decision rule: confidence >= confidence_threshold_auto_adopt
AND quality_level == pass AND level not requiring approval
-> status = available; otherwise review_required with reason.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.rules_config import GovernanceRulesConfig
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType, GovernanceResultStatus
from nexus_app.governance.schemas import AdoptionStatus, DecisionTrailEntry

logger = logging.getLogger(__name__)


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
            tags=ai_output.get("tags", []),
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
                "rules_schema_version": rules_snapshot["schema_version"],
            },
            actor_id=user_id,
        )
        return result

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
        suggestion = ai_output.get("tags", [])
        valid_codes = {t.code for t in config.tags}

        checks: dict[str, Any] = {
            "confidence_threshold_auto_adopt": threshold,
            "actual_confidence": confidence,
            "valid_tags": sorted(valid_codes),
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

        invalid = [t for t in suggestion if t not in valid_codes]
        if invalid:
            return DecisionTrailEntry(
                field_name="tags",
                ai_suggestion=suggestion,
                ai_confidence=confidence,
                threshold_check=checks,
                final_value=[t for t in suggestion if t in valid_codes],
                adoption_status="review_required",
                review_reason=f"invalid tags {invalid} not in valid set",
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
        thresholds = config.quality_scoring.thresholds

        checks: dict[str, Any] = {
            "pass_threshold": thresholds.pass_,
            "warning_threshold": thresholds.warning,
            "review_required_below": thresholds.review_required_below,
            "actual_score": score,
            "actual_level": quality_level,
        }

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
