"""Immutable business-expert governance review decisions.

The service is deliberately downstream of AI governance: it never changes an
``AIGovernanceRun`` or its source ``GovernanceResult``. A submission writes an
immutable decision, a new official result snapshot, and expert-final retrieval
tag rows in one caller-owned transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.governance_tag_projection import BUCKET_TO_TAG_TYPE
from nexus_app.ai_governance.knowledge_type_inference import (
    infer_knowledge_emissions_for_classification,
)
from nexus_app.ai_governance.tag_normalization import normalize_tag_value
from nexus_app.ai_governance.tag_payload import StructuredTagBag, normalize_to_structured
from nexus_app.ai_governance.tag_projection import TagRowPayload, persist_tag_rows
from nexus_app.audit import write_audit
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    GovernanceResultStatus,
    JobStatus,
    JobType,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.governance.schemas import DecisionTrailEntry
from nexus_app.metadata.version_state import VersionStateManager
from nexus_app.pipeline.payload_schema import JOB_PAYLOAD_SCHEMA_VERSION
from nexus_app.worker.notify import notify_job_ready


class GovernanceReviewError(ValueError):
    """A submission cannot produce an official governance review result."""


class StaleGovernanceReviewError(GovernanceReviewError):
    """The submitted base result is no longer the latest result for its ref."""


QualityDisposition = Literal["pass", "review_required"]


@dataclass(frozen=True)
class GovernanceReviewSubmission:
    classification: str
    level: str
    org_scope: str
    tags: StructuredTagBag
    quality_disposition: QualityDisposition
    quality_reason: str
    review_reason: str
    feedback_labels: list[str]


@dataclass(frozen=True)
class GovernanceReviewOutcome:
    decision: models.GovernanceReviewDecision
    result: models.GovernanceResult
    version: models.AssetVersion
    is_admissible: bool
    continuation_job: models.Job | None = None


def parse_submission(payload: dict[str, Any]) -> GovernanceReviewSubmission:
    try:
        tags = StructuredTagBag.model_validate(payload.get("tags"))
    except Exception as exc:
        raise GovernanceReviewError(f"invalid structured tags: {exc}") from exc

    classification = str(payload.get("classification") or "").strip()
    level = str(payload.get("level") or "").strip()
    org_scope = str(payload.get("org_scope") or "").strip()
    review_reason = str(payload.get("review_reason") or "").strip()
    quality = payload.get("quality_review")
    if not isinstance(quality, dict):
        raise GovernanceReviewError("quality_review is required")
    disposition = quality.get("disposition")
    quality_reason = str(quality.get("reason") or "").strip()

    if not classification or not level or not org_scope:
        raise GovernanceReviewError("classification, level, and org_scope are required")
    if not review_reason:
        raise GovernanceReviewError("review_reason is required")
    if disposition not in {"pass", "review_required"}:
        raise GovernanceReviewError("quality_review.disposition must be pass or review_required")
    if not quality_reason:
        raise GovernanceReviewError("quality_review.reason is required")

    feedback_labels = payload.get("feedback_labels") or []
    if not isinstance(feedback_labels, list) or not all(isinstance(v, str) for v in feedback_labels):
        raise GovernanceReviewError("feedback_labels must be a list of strings")
    return GovernanceReviewSubmission(
        classification=classification,
        level=level,
        org_scope=org_scope,
        tags=tags,
        quality_disposition=disposition,
        quality_reason=quality_reason,
        review_reason=review_reason,
        feedback_labels=list(dict.fromkeys(v.strip() for v in feedback_labels if v.strip())),
    )


class GovernanceReviewService:
    def __init__(self, rules_registry: Any) -> None:
        self._registry = rules_registry

    def submit(
        self,
        session: Session,
        *,
        base_result_id: str,
        submission: GovernanceReviewSubmission,
        reviewer_id: str,
        idempotency_key: str,
        trace_id: str | None,
    ) -> GovernanceReviewOutcome:
        base = session.scalar(
            select(models.GovernanceResult)
            .where(models.GovernanceResult.id == base_result_id)
            .with_for_update()
        )
        if base is None:
            raise GovernanceReviewError(f"governance result '{base_result_id}' not found")
        if base.status != GovernanceResultStatus.REVIEW_REQUIRED:
            raise GovernanceReviewError("governance result is not pending review")

        replay = session.scalar(
            select(models.GovernanceReviewDecision).where(
                models.GovernanceReviewDecision.base_governance_result_id == base.id,
                models.GovernanceReviewDecision.idempotency_key == idempotency_key,
            )
        )
        if replay is not None:
            result = replay.resulting_governance_result
            ref = session.get(models.NormalizedAssetRef, replay.normalized_ref_id)
            version = session.get(models.AssetVersion, ref.version_id) if ref is not None else None
            if result is None or version is None:  # pragma: no cover - FK corruption guard
                raise GovernanceReviewError("idempotent review replay has broken references")
            return GovernanceReviewOutcome(
                decision=replay,
                result=result,
                version=version,
                is_admissible=version.version_status == AssetVersionStatus.AVAILABLE,
                continuation_job=session.scalar(
                    select(models.Job)
                    .where(
                        models.Job.job_type == JobType.KNOWLEDGE_CONTINUATION,
                        models.Job.idempotency_key == f"governance-review:{replay.id}",
                    )
                    .order_by(models.Job.created_at.desc())
                    .limit(1)
                ),
            )

        latest_id = session.scalar(
            select(models.GovernanceResult.id)
            .where(models.GovernanceResult.normalized_ref_id == base.normalized_ref_id)
            .order_by(models.GovernanceResult.created_at.desc())
            .limit(1)
        )
        if latest_id != base.id:
            raise StaleGovernanceReviewError(
                "the submitted governance result is no longer current; reload review context"
            )

        valid_classifications = {item.code for item in self._registry.get_classifications()}
        valid_levels = {item.code for item in self._registry.get_levels()}
        if submission.classification not in valid_classifications:
            raise GovernanceReviewError("classification is not valid under the active governance rules")
        if submission.level not in valid_levels:
            raise GovernanceReviewError("level is not valid under the active governance rules")

        ref = session.get(models.NormalizedAssetRef, base.normalized_ref_id)
        if ref is None:  # pragma: no cover - FK corruption guard
            raise GovernanceReviewError("base governance result normalized ref is missing")
        version = session.get(models.AssetVersion, ref.version_id)
        if version is None:  # pragma: no cover - FK corruption guard
            raise GovernanceReviewError("normalized ref version is missing")

        # Pipeline routing is a queue-time contract. A continuation must copy
        # that persisted value from the original ingest job, never re-infer it
        # from the asset or MIME type during review/worker execution.
        original_pipeline_type = self._original_pipeline_type(session, version)

        decision_id = models.new_uuid()
        trail = self._build_final_trail(base, submission, decision_id, reviewer_id)
        quality_summary = self._final_quality_summary(base, submission, decision_id, reviewer_id)
        is_admissible = (
            submission.quality_disposition == "pass"
            and all(entry["adoption_status"] != "review_required" for entry in trail)
        )
        result = models.GovernanceResult(
            normalized_ref_id=ref.id,
            ai_run_id=base.ai_run_id,
            classification=submission.classification,
            level=submission.level,
            tags=submission.tags.model_dump(mode="json"),
            org_scope=submission.org_scope,
            index_admission=is_admissible,
            quality_summary=quality_summary,
            decision_trail=trail,
            rules_schema_version=base.rules_schema_version,
            rules_content_hash=base.rules_content_hash,
            rules_version_id=base.rules_version_id,
            status=(
                GovernanceResultStatus.AVAILABLE
                if is_admissible
                else GovernanceResultStatus.REVIEW_REQUIRED
            ),
            created_by=reviewer_id,
            trace_id=trace_id,
        )
        session.add(result)
        session.flush()

        decision = models.GovernanceReviewDecision(
            id=decision_id,
            normalized_ref_id=ref.id,
            base_governance_result_id=base.id,
            base_ai_run_id=base.ai_run_id,
            resulting_governance_result_id=result.id,
            decision_payload={
                "classification": submission.classification,
                "level": submission.level,
                "org_scope": submission.org_scope,
                "tags": submission.tags.model_dump(mode="json"),
                "quality_review": {
                    "disposition": submission.quality_disposition,
                    "reason": submission.quality_reason,
                },
            },
            review_reason=submission.review_reason,
            feedback_labels=submission.feedback_labels,
            reviewer_id=reviewer_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
        session.add(decision)
        self._project_expert_tags(session, ref, version, submission.tags, trace_id)
        self._materialize_final_knowledge_emissions(
            session,
            ref,
            submission.classification,
            trace_id=trace_id,
        )

        state_manager = VersionStateManager()
        target_status = state_manager.determine_version_status(session, result)
        if target_status == AssetVersionStatus.AVAILABLE:
            state_manager.transition_to_available(
                session, version, result, user_id=reviewer_id, trace_id=trace_id
            )
        else:
            state_manager.transition_to_review_required(
                session, version, result, user_id=reviewer_id, trace_id=trace_id
            )

        continuation_job: models.Job | None = None
        if version.version_status == AssetVersionStatus.AVAILABLE:
            if original_pipeline_type is None:
                raise GovernanceReviewError(
                    "cannot continue knowledge pipeline: original pipeline_type is unavailable"
                )
            continuation_job = self._queue_knowledge_continuation(
                session,
                decision=decision,
                ref=ref,
                version=version,
                pipeline_type=original_pipeline_type,
                trace_id=trace_id,
                reviewer_id=reviewer_id,
            )

        write_audit(
            session,
            AuditEventType.GOVERNANCE_REVIEW_DECISION_SUBMITTED,
            "governance_review_decision",
            decision.id,
            trace_id,
            {
                "normalized_ref_id": ref.id,
                "base_governance_result_id": base.id,
                "resulting_governance_result_id": result.id,
                "version_id": version.id,
                "version_status": version.version_status.value,
                "quality_disposition": submission.quality_disposition,
                "tag_counts": _tag_counts(submission.tags),
            },
            actor_type="user",
            actor_id=reviewer_id,
        )
        session.flush()
        return GovernanceReviewOutcome(
            decision=decision,
            result=result,
            version=version,
            is_admissible=is_admissible,
            continuation_job=continuation_job,
        )

    @staticmethod
    def _original_pipeline_type(
        session: Session, version: models.AssetVersion
    ) -> str | None:
        if version.raw_object_id is None:
            return None
        job = session.scalar(
            select(models.Job)
            .where(
                models.Job.raw_object_id == version.raw_object_id,
                models.Job.job_type == JobType.INGEST_PROCESS,
            )
            .order_by(models.Job.created_at.asc())
            .limit(1)
        )
        value = (job.payload or {}).get("pipeline_type") if job is not None else None
        return value if value in {"document", "record"} else None

    @staticmethod
    def _queue_knowledge_continuation(
        session: Session,
        *,
        decision: models.GovernanceReviewDecision,
        ref: models.NormalizedAssetRef,
        version: models.AssetVersion,
        pipeline_type: str,
        trace_id: str | None,
        reviewer_id: str,
    ) -> models.Job:
        job = models.Job(
            job_type=JobType.KNOWLEDGE_CONTINUATION,
            status=JobStatus.QUEUED,
            ingest_batch_id=version.raw_object.batch_id if version.raw_object else None,
            raw_object_id=version.raw_object_id,
            idempotency_key=f"governance-review:{decision.id}",
            current_stage="queued",
            trace_id=trace_id,
            payload={
                "normalized_ref_id": ref.id,
                "asset_version_id": version.id,
                "pipeline_type": pipeline_type,
                "trigger": "governance_review",
            },
            payload_schema_version=JOB_PAYLOAD_SCHEMA_VERSION,
            metadata_summary={"pipeline": "knowledge_continuation"},
        )
        session.add(job)
        session.flush()
        write_audit(
            session,
            AuditEventType.KNOWLEDGE_CONTINUATION_QUEUED,
            "job",
            job.id,
            trace_id,
            {
                "governance_review_decision_id": decision.id,
                "normalized_ref_id": ref.id,
                "asset_version_id": version.id,
                "pipeline_type": pipeline_type,
            },
            actor_type="user",
            actor_id=reviewer_id,
        )
        notify_job_ready(session)
        return job

    def _materialize_final_knowledge_emissions(
        self,
        session: Session,
        ref: models.NormalizedAssetRef,
        classification: str,
        *,
        trace_id: str | None,
    ) -> None:
        """Replace pre-review emissions with the final official classification."""
        summary = dict(ref.metadata_summary or {})
        summary["knowledge_emissions"] = infer_knowledge_emissions_for_classification(
            classification, self._registry, confidence=1.0
        )
        ref.metadata_summary = summary

        from nexus_app.major_profile.presentation import reconcile_presentation

        suppressed_projection = reconcile_presentation(ref, classification)
        if suppressed_projection is not None:
            write_audit(
                session,
                AuditEventType.DOMAIN_NORMALIZE_COMPLETED,
                "normalized_asset_ref",
                ref.id,
                trace_id,
                {"action": "presentation_projection_suppressed", **suppressed_projection},
            )

    @staticmethod
    def _build_final_trail(
        base: models.GovernanceResult,
        submission: GovernanceReviewSubmission,
        decision_id: str,
        reviewer_id: str,
    ) -> list[dict[str, Any]]:
        original_by_field = {
            item.get("field_name"): item
            for item in (base.decision_trail or [])
            if isinstance(item, dict)
        }
        values = {
            "classification": submission.classification,
            "level": submission.level,
            "tags": submission.tags.model_dump(mode="json"),
            "quality": submission.quality_disposition,
        }
        before_values = {
            "classification": base.classification,
            "level": base.level,
            "tags": normalize_to_structured(base.tags).model_dump(mode="json"),
            "quality": (base.quality_summary or {}).get("quality_level"),
        }
        trail: list[dict[str, Any]] = []
        for field_name, final_value in values.items():
            old = original_by_field.get(field_name, {})
            before = before_values[field_name]
            status = "human_confirmed" if before == final_value else "human_overridden"
            entry = DecisionTrailEntry(
                field_name=field_name,  # type: ignore[arg-type]
                ai_suggestion=old.get("ai_suggestion", before),
                ai_confidence=float(old.get("ai_confidence") or 0),
                threshold_check=old.get("threshold_check") or {},
                final_value=final_value,
                adoption_status=status,  # type: ignore[arg-type]
                review_reason=None,
                review_decision_id=decision_id,
                reviewer_id=reviewer_id,
                reviewed_at=models.utcnow().isoformat(),
                before_value=before,
            )
            trail.append(entry.model_dump())
        return trail

    @staticmethod
    def _final_quality_summary(
        base: models.GovernanceResult,
        submission: GovernanceReviewSubmission,
        decision_id: str,
        reviewer_id: str,
    ) -> dict[str, Any]:
        original = dict(base.quality_summary or {})
        final = dict(original)
        final["ai_assessment"] = original
        final["quality_level"] = "pass" if submission.quality_disposition == "pass" else "warning"
        final["blocking_reasons"] = [] if submission.quality_disposition == "pass" else original.get("blocking_reasons") or []
        final["manual_review"] = {
            "disposition": submission.quality_disposition,
            "reason": submission.quality_reason,
            "decision_id": decision_id,
            "reviewer_id": reviewer_id,
        }
        return final

    @staticmethod
    def _project_expert_tags(
        session: Session,
        ref: models.NormalizedAssetRef,
        version: models.AssetVersion,
        tags: StructuredTagBag,
        trace_id: str | None,
    ) -> None:
        payloads: list[TagRowPayload] = []
        raw = tags.model_dump(mode="json")
        for bucket, tag_type in BUCKET_TO_TAG_TYPE.items():
            entries = raw.get(bucket, [])
            for entry in entries:
                if bucket == "time_ranges":
                    value = _time_range_display(entry)
                else:
                    value = entry.get("value") if isinstance(entry, dict) else None
                if not isinstance(value, str):  # guarded by StructuredTagBag
                    continue
                normalized = normalize_tag_value(value, tag_type)
                if not normalized:
                    continue
                payloads.append(TagRowPayload(
                    tag_type=tag_type,
                    tag_value=value,
                    tag_value_normalized=normalized,
                    target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
                    target_id=ref.id,
                    asset_version_id=version.id,
                    source=TagAssetIndexSource.EXPERT_MANUAL,
                    confidence=1.0,
                    extraction_run_id=None,
                    trace_id=trace_id,
                    evidence_span=None,
                ))
        persist_tag_rows(
            session,
            payloads,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=ref.id,
            source=TagAssetIndexSource.EXPERT_MANUAL,
        )


def _time_range_display(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    kind = entry.get("kind")
    if kind == "year_range":
        start, end = entry.get("start"), entry.get("end")
        return str(start) if start == end else f"{start}-{end}"
    if kind == "point_in_time":
        return str(entry.get("year"))
    return str(kind or "")


def _tag_counts(tags: StructuredTagBag) -> dict[str, int]:
    raw = tags.model_dump(mode="json")
    return {bucket: len(values) for bucket, values in raw.items() if isinstance(values, list)}
