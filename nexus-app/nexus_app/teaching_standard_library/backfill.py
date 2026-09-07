"""Dry-run-first historical projection for professional teaching standards."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import LiteLLMClientProtocol
from nexus_app.audit import write_audit
from nexus_app.enums import (
    AuditEventType,
    NormalizedAssetRefStatus,
    NormalizedType,
)
from nexus_app.storage import ObjectStorage
from nexus_app.teaching_standard_library.course_extractor import (
    extract as extract_courses,
)
from nexus_app.teaching_standard_library.course_writer import (
    source_fact_hashes,
    write as write_courses,
)
from nexus_app.teaching_standard_library.derivation_service import (
    derive_library,
    preview_derivation_model,
    preview_library_derivation,
)
from nexus_app.teaching_standard_library.extractor import extract
from nexus_app.teaching_standard_library.writer import source_fact_digest
from nexus_app.teaching_standard_library.writer import write as write_library

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillRefOutcome:
    normalized_ref_id: str
    title: str | None
    ok: bool
    action: str
    reason: str
    course_count: int = 0
    projection_written: bool = False
    llm_required: bool = False
    effective_model_source: str = "missing"
    library_id: str | None = None
    derivation_run_id: str | None = None
    failure_code: str | None = None


@dataclass
class BackfillOutcome:
    dry_run: bool
    refs_seen: int = 0
    candidate_count: int = 0
    skipped_count: int = 0
    projected_count: int = 0
    derived_count: int = 0
    reused_count: int = 0
    failed_count: int = 0
    llm_required_count: int = 0
    profile_model_count: int = 0
    environment_model_count: int = 0
    failure_summary: dict[str, int] = field(default_factory=dict)
    refs: list[BackfillRefOutcome] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "refs_seen": self.refs_seen,
            "candidate_count": self.candidate_count,
            "skipped_count": self.skipped_count,
            "projected_count": self.projected_count,
            "derived_count": self.derived_count,
            "reused_count": self.reused_count,
            "failed_count": self.failed_count,
            "llm_required_count": self.llm_required_count,
            "profile_model_count": self.profile_model_count,
            "environment_model_count": self.environment_model_count,
            "failure_summary": dict(sorted(self.failure_summary.items())),
            "refs": [asdict(item) for item in self.refs],
        }


def run_backfill(
    session: Session,
    *,
    storage: ObjectStorage,
    llm_client: LiteLLMClientProtocol | None,
    default_governance_model: str,
    apply_changes: bool,
    ref_id: str | None = None,
    limit: int | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    retry_failed: bool = False,
    no_llm: bool = False,
    trace_id: str | None = None,
) -> BackfillOutcome:
    """Plan or execute a bounded, per-ref-isolated historical backfill."""
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if from_date is not None and to_date is not None and from_date >= to_date:
        raise ValueError("from_date must be earlier than to_date")

    outcome = BackfillOutcome(dry_run=not apply_changes)
    for normalized_ref in _candidate_refs(
        session,
        ref_id=ref_id,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
    ):
        outcome.refs_seen += 1
        try:
            item, is_candidate = _process_ref(
                session,
                normalized_ref,
                storage=storage,
                llm_client=llm_client,
                default_governance_model=default_governance_model,
                apply_changes=apply_changes,
                retry_failed=retry_failed,
                no_llm=no_llm,
                trace_id=trace_id,
            )
        except Exception as exc:  # noqa: BLE001 - isolate each historical ref
            session.rollback()
            logger.warning(
                "teaching-standard backfill failed for normalized_ref=%s: %s",
                normalized_ref.id,
                type(exc).__name__,
            )
            item = BackfillRefOutcome(
                normalized_ref_id=normalized_ref.id,
                title=_bounded_title(normalized_ref.title),
                ok=False,
                action="failed",
                reason="backfill_ref_failed",
                failure_code="backfill_ref_failed",
            )
            is_candidate = False
        _record_outcome(outcome, item, is_candidate=is_candidate)
    return outcome


def _candidate_refs(
    session: Session,
    *,
    ref_id: str | None,
    limit: int | None,
    from_date: datetime | None,
    to_date: datetime | None,
) -> list[models.NormalizedAssetRef]:
    latest_classification = (
        select(models.GovernanceResult.classification)
        .where(
            models.GovernanceResult.normalized_ref_id == models.NormalizedAssetRef.id
        )
        .order_by(
            models.GovernanceResult.created_at.desc(),
            models.GovernanceResult.id.desc(),
        )
        .limit(1)
        .correlate(models.NormalizedAssetRef)
        .scalar_subquery()
    )
    stmt = (
        select(models.NormalizedAssetRef)
        .where(
            models.NormalizedAssetRef.normalized_type == NormalizedType.DOCUMENT,
            models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED,
            latest_classification == "teaching_standard",
        )
        .order_by(
            models.NormalizedAssetRef.created_at,
            models.NormalizedAssetRef.id,
        )
    )
    if ref_id is not None:
        stmt = stmt.where(models.NormalizedAssetRef.id == ref_id)
    if from_date is not None:
        stmt = stmt.where(models.NormalizedAssetRef.created_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(models.NormalizedAssetRef.created_at < to_date)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def _process_ref(
    session: Session,
    normalized_ref: models.NormalizedAssetRef,
    *,
    storage: ObjectStorage,
    llm_client: LiteLLMClientProtocol | None,
    default_governance_model: str,
    apply_changes: bool,
    retry_failed: bool,
    no_llm: bool,
    trace_id: str | None,
) -> tuple[BackfillRefOutcome, bool]:
    title = _bounded_title(normalized_ref.title)
    try:
        payload = json.loads(
            storage.get_bytes(_storage_key(normalized_ref.object_uri)).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                False,
                "failed",
                "normalized_document_invalid",
                failure_code="normalized_document_invalid",
            ),
            False,
        )
    if not isinstance(payload, dict):
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                False,
                "failed",
                "normalized_document_invalid",
                failure_code="normalized_document_invalid",
            ),
            False,
        )

    standard_projection = extract(payload)
    if standard_projection is None:
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                True,
                "skip",
                "not_teaching_standard",
            ),
            False,
        )
    course_projection = extract_courses(payload)
    if course_projection is None:
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                False,
                "failed",
                "course_projection_invalid",
                failure_code="course_projection_invalid",
            ),
            True,
        )
    course_count = len(course_projection.get("courses", []))
    if course_count == 0:
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                True,
                "skip",
                "course_facts_missing",
            ),
            False,
        )

    existing = session.scalar(
        select(models.TeachingStandardLibrary).where(
            models.TeachingStandardLibrary.normalized_ref_id == normalized_ref.id
        )
    )
    if retry_failed and not _latest_derivation_failed(session, existing):
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                True,
                "skip",
                "retry_not_applicable",
                course_count=course_count,
                library_id=existing.id if existing is not None else None,
            ),
            True,
        )
    if existing is not None and existing.status != "review":
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                True,
                "skip",
                "library_not_review",
                course_count=course_count,
                library_id=existing.id,
            ),
            True,
        )

    current = _projection_is_current(existing, standard_projection, course_projection)
    if not apply_changes:
        return (
            _plan_ref(
                session,
                normalized_ref,
                existing,
                current=current,
                course_count=course_count,
                default_governance_model=default_governance_model,
                no_llm=no_llm,
            ),
            True,
        )

    library = write_library(session, normalized_ref, standard_projection)
    if library is None:
        raise ValueError("standard projection failed writer validation")
    courses = write_courses(session, library, course_projection)
    write_audit(
        session,
        AuditEventType.TEACHING_STANDARD_LIBRARY_GENERATED,
        "teaching_standard_library",
        library.id,
        trace_id,
        {
            "normalized_ref_id": normalized_ref.id,
            "status": library.status,
            "course_count": len(courses),
            "backfill": True,
            "course_diagnostic_keys": sorted(
                key
                for key, value in (course_projection.get("diagnostics") or {}).items()
                if value
            ),
        },
        actor_type="system",
        actor_id="teaching_standard_backfill",
    )
    if no_llm or not courses:
        session.commit()
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                True,
                "project",
                "projected_without_derivation" if no_llm else "course_facts_missing",
                course_count=len(courses),
                projection_written=True,
                llm_required=False,
                effective_model_source=_model_source(session, default_governance_model),
                library_id=library.id,
            ),
            True,
        )

    preview = preview_library_derivation(
        session,
        library,
        default_governance_model=default_governance_model,
    )
    result = derive_library(
        session,
        library,
        llm_client=llm_client,
        default_governance_model=default_governance_model,
        trace_id=trace_id,
    )
    session.commit()
    if result.status != "completed":
        return (
            BackfillRefOutcome(
                normalized_ref.id,
                title,
                False,
                "derive",
                "derivation_failed",
                course_count=len(courses),
                projection_written=True,
                llm_required=preview.call_required,
                effective_model_source=preview.effective_model_source,
                library_id=library.id,
                derivation_run_id=result.run_id,
                failure_code=result.failure_code,
            ),
            True,
        )
    return (
        BackfillRefOutcome(
            normalized_ref.id,
            title,
            True,
            "reuse" if result.reused else "derive",
            "derivation_reused" if result.reused else "derivation_completed",
            course_count=len(courses),
            projection_written=True,
            llm_required=preview.call_required,
            effective_model_source=preview.effective_model_source,
            library_id=library.id,
            derivation_run_id=result.run_id,
        ),
        True,
    )


def _plan_ref(
    session: Session,
    normalized_ref: models.NormalizedAssetRef,
    existing: models.TeachingStandardLibrary | None,
    *,
    current: bool,
    course_count: int,
    default_governance_model: str,
    no_llm: bool,
) -> BackfillRefOutcome:
    title = _bounded_title(normalized_ref.title)
    if no_llm or course_count == 0:
        return BackfillRefOutcome(
            normalized_ref.id,
            title,
            True,
            "project" if existing is None else "rebuild",
            "dry_run_without_derivation",
            course_count=course_count,
            library_id=existing.id if existing is not None else None,
            effective_model_source=_model_source(session, default_governance_model),
        )
    if existing is not None and current:
        preview = preview_library_derivation(
            session,
            existing,
            default_governance_model=default_governance_model,
        )
        if preview.failure_code is not None:
            return BackfillRefOutcome(
                normalized_ref.id,
                title,
                False,
                "derive",
                "derivation_preflight_failed",
                course_count=course_count,
                effective_model_source=preview.effective_model_source,
                library_id=existing.id,
                failure_code=preview.failure_code,
            )
        return BackfillRefOutcome(
            normalized_ref.id,
            title,
            True,
            "reuse" if preview.reusable else "derive",
            "dry_run_would_reuse" if preview.reusable else "dry_run_would_derive",
            course_count=course_count,
            llm_required=preview.call_required,
            effective_model_source=preview.effective_model_source,
            library_id=existing.id,
        )
    model_source, failure_code = _model_readiness(session, default_governance_model)
    if failure_code is not None:
        return BackfillRefOutcome(
            normalized_ref.id,
            title,
            False,
            "derive",
            "derivation_preflight_failed",
            course_count=course_count,
            effective_model_source=model_source,
            library_id=existing.id if existing is not None else None,
            failure_code=failure_code,
        )
    return BackfillRefOutcome(
        normalized_ref.id,
        title,
        True,
        "project" if existing is None else "rebuild",
        "dry_run_would_project_and_derive",
        course_count=course_count,
        llm_required=True,
        effective_model_source=model_source,
        library_id=existing.id if existing is not None else None,
    )


def _projection_is_current(
    library: models.TeachingStandardLibrary | None,
    standard_projection: dict[str, Any],
    course_projection: dict[str, Any],
) -> bool:
    if library is None or library.hash_digest != source_fact_digest(
        standard_projection
    ):
        return False
    desired = source_fact_hashes(course_projection)
    current = {
        (course.course_type, course.standard_course_name): course.source_hash
        for course in library.courses
    }
    return desired is not None and desired == current


def _latest_derivation_failed(
    session: Session, library: models.TeachingStandardLibrary | None
) -> bool:
    if library is None:
        return False
    latest = session.scalars(
        select(models.TeachingStandardDerivationRun)
        .where(models.TeachingStandardDerivationRun.library_id == library.id)
        .order_by(models.TeachingStandardDerivationRun.created_at.desc())
    ).first()
    return latest is not None and latest.status == "failed"


def _model_source(session: Session, default_governance_model: str) -> str:
    return preview_derivation_model(
        session,
        default_governance_model=default_governance_model,
    ).effective_model_source


def _model_readiness(
    session: Session, default_governance_model: str
) -> tuple[str, str | None]:
    preview = preview_derivation_model(
        session,
        default_governance_model=default_governance_model,
    )
    return preview.effective_model_source, preview.failure_code


def _record_outcome(
    outcome: BackfillOutcome,
    item: BackfillRefOutcome,
    *,
    is_candidate: bool,
) -> None:
    outcome.refs.append(item)
    if is_candidate:
        outcome.candidate_count += 1
    if item.action == "skip":
        outcome.skipped_count += 1
    if item.projection_written:
        outcome.projected_count += 1
    if item.reason == "derivation_completed":
        outcome.derived_count += 1
    if item.reason in {"derivation_reused", "dry_run_would_reuse"}:
        outcome.reused_count += 1
    if not item.ok:
        outcome.failed_count += 1
        failure = item.failure_code or item.reason
        outcome.failure_summary[failure] = outcome.failure_summary.get(failure, 0) + 1
    if item.llm_required:
        outcome.llm_required_count += 1
        if item.effective_model_source == "profile":
            outcome.profile_model_count += 1
        elif item.effective_model_source == "environment":
            outcome.environment_model_count += 1


def _storage_key(object_uri: str) -> str:
    return (
        object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri
    )


def _bounded_title(value: str | None) -> str | None:
    return value[:160] if value else None


__all__ = [
    "BackfillOutcome",
    "BackfillRefOutcome",
    "run_backfill",
]
