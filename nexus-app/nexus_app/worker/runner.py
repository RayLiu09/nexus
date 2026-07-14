from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.config import Settings, get_settings
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    IngestBatchStatus,
    JobStatus,
    NormalizedType,
    PipelineType,
    RawObjectStatus,
    StageStatus,
)
from nexus_app.image_analysis import ImageAnalyzer, get_image_analyzer
from nexus_app.ingest.batch import update_batch_aggregate_status
from nexus_app.ingest.config_loader import (
    IngestValidateRegistry,
    get_ingest_validate_registry,
)
from nexus_app.ingest.gateway import CSV_MIME_TYPES, XLSX_MIME_TYPES
from nexus_app.mineru import MinerUAdapter, get_mineru_adapter
from nexus_app.models import utcnow
from nexus_app.normalize.service import NormalizeService
from nexus_app.pipeline.context import PipelineContext
from nexus_app.pipeline.payload_schema import SUPPORTED_JOB_PAYLOAD_VERSIONS
from nexus_app.profile_detect import (
    DEFAULT_AUTO_ADMIT_THRESHOLD,
    ProfileDetectResult,
    detect,
)
from nexus_app.structured_parse import (
    CorruptSourceError,
    StructuredParseError,
    parse_csv,
    parse_xlsx,
)
from nexus_app.structured_parse.schemas import ParsedWorkbook
from nexus_app.pipeline.stages import (
    run_assetize,
    run_governance_decision,
    run_index_submit,
    run_knowledge_chunking,
    run_normalize_document,
    run_normalize_record,
    run_parse,
)
from nexus_app.storage import ObjectStorage, get_object_storage

logger = logging.getLogger(__name__)

_RETRY_DELAYS_SECONDS = [60, 300, 900]


class RetryableError(Exception):
    """Transient error — job should be retried with backoff."""


class NonRetryableError(Exception):
    """Permanent failure — job should not be retried."""
    def __init__(self, msg: str, error_code: str = "non_retryable") -> None:
        super().__init__(msg)
        self.error_code = error_code


def _backoff_seconds(attempt_count: int) -> int:
    idx = max(0, min(attempt_count - 1, len(_RETRY_DELAYS_SECONDS) - 1))
    return _RETRY_DELAYS_SECONDS[idx]


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, RetryableError):
        return "retryable"
    if isinstance(exc, NonRetryableError):
        return "non_retryable"
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if any(w in name or w in msg for w in ("timeout", "connection", "unavailable", "deadlock", "operationalerror")):
        return "retryable"
    return "non_retryable"


def _release_lock(job: models.Job) -> None:
    job.locked_by = None
    job.lock_expires_at = None


def _build_normalize_service(settings: Settings) -> NormalizeService:
    """Construct NormalizeService for the worker.

    When LiteLLM is configured we attach the default client so the service can
    perform LLM-based summary generation and field extraction. When LiteLLM is
    unavailable we still return a NormalizeService (without LLM client) so the
    deterministic snippet/summary fallback and rule-engine validation still run.
    """
    try:
        from nexus_app.ai_governance.services import _create_default_litellm_client

        llm_client = _create_default_litellm_client(settings)
    except Exception as exc:  # noqa: BLE001 defensive: never fail pipeline boot on LiteLLM config
        logger.warning(
            "NormalizeService LiteLLM client unavailable, running without LLM enhancement: %s",
            exc,
        )
        llm_client = None
    model_alias = settings.default_normalize_model or settings.default_governance_model
    return NormalizeService(llm_client=llm_client, llm_model_alias=model_alias)


def _add_failure_stage(session: Session, job: models.Job, stage_name: str, reason: str) -> None:
    now = utcnow()
    existing = session.scalar(
        select(models.JobStage)
        .where(
            models.JobStage.job_id == job.id,
            models.JobStage.stage_name == stage_name,
            models.JobStage.status.in_([StageStatus.RUNNING, StageStatus.FAILED]),
        )
        .order_by(models.JobStage.created_at.desc())
    )
    if existing is not None:
        existing.status = StageStatus.FAILED
        existing.finished_at = existing.finished_at or now
        existing.failure_reason = reason[:2000]
        session.flush()
        return

    stage = models.JobStage(
        job_id=job.id,
        stage_name=stage_name,
        status=StageStatus.FAILED,
        started_at=now,
        finished_at=now,
        failure_reason=reason[:2000],
        detail={},
    )
    session.add(stage)
    session.flush()


def _safe_pipeline_failed_audit(
    session: Session,
    job_id: str,
    trace_id: str | None,
    summary: dict[str, Any],
) -> None:
    # Audit-write isolation: a poisoned audit row (e.g. enum-drift between
    # Python AuditEventType and the Postgres enum) must NOT prevent the
    # job-state commit. Run the write inside a SAVEPOINT so its failure
    # rolls back only the audit insert, leaving the job's FAILED/DEAD_LETTERED
    # state on the session for the surrounding commit.
    try:
        with session.begin_nested():
            write_audit(
                session,
                AuditEventType.PIPELINE_FAILED,
                "job",
                job_id,
                trace_id,
                summary,
            )
    except Exception:  # noqa: BLE001 — audit is best-effort; job state takes precedence
        logger.exception(
            "PIPELINE_FAILED audit write failed for job=%s; job state will still commit",
            job_id,
        )


def _mark_job_outcome(
    session: Session,
    job: models.Job,
    reason: str,
    trace_id: str | None,
    exc: Exception,
) -> None:
    classification = _classify_error(exc)
    error_code = getattr(exc, "error_code", "pipeline_error")
    _release_lock(job)

    if classification == "retryable" and job.attempt_count < job.max_attempts:
        delay = _backoff_seconds(job.attempt_count)
        job.status = JobStatus.QUEUED
        job.next_run_at = utcnow() + timedelta(seconds=delay)
        job.failure_reason = reason[:2000]
        job.last_error_message = reason[:2000]
        _maybe_aggregate_batch(session, job)
        return
    elif job.attempt_count >= job.max_attempts:
        job.status = JobStatus.DEAD_LETTERED
        job.failure_reason = reason[:2000]
        job.last_error_code = "max_attempts_exceeded"
        job.last_error_message = reason[:2000]
        _safe_pipeline_failed_audit(
            session,
            job.id,
            trace_id,
            {"error_code": "dead_lettered", "reason": reason[:500], "attempt_count": job.attempt_count},
        )
    else:
        job.status = JobStatus.FAILED
        job.failure_reason = reason[:2000]
        job.last_error_code = error_code
        job.last_error_message = reason[:2000]
        _safe_pipeline_failed_audit(
            session,
            job.id,
            trace_id,
            {"error_code": error_code, "reason": reason[:500]},
        )
    _maybe_aggregate_batch(session, job)


def _maybe_aggregate_batch(session: Session, job: models.Job) -> None:
    """Recompute the parent batch's aggregate status if the job belongs to one.

    Called after every job-state transition (terminal or retry) so the batch's
    rollup remains consistent with all owned jobs.
    """
    if job.ingest_batch_id is None:
        return
    try:
        update_batch_aggregate_status(session, job.ingest_batch_id)
    except Exception:
        logger.exception("batch aggregation failed for batch_id=%s", job.ingest_batch_id)


# ---------------------------------------------------------------------------
# Pipeline-specific stage runners
# ---------------------------------------------------------------------------

def _run_document_pipeline(
    ctx: PipelineContext,
    version: models.AssetVersion,
) -> models.NormalizedAssetRef:
    """Pipeline A: parse (MinerU) → normalize_document."""
    artifact = run_parse(ctx, version)
    return run_normalize_document(ctx, version, artifact)


def _run_record_pipeline(
    ctx: PipelineContext,
    version: models.AssetVersion,
    raw_payload: dict[str, Any],
    *,
    profile_dict: dict[str, Any] | None = None,
) -> models.NormalizedAssetRef:
    """Pipeline B: normalize_record (no parse stage).

    Args:
        profile_dict: Optional ProfileDetectResult dict. When given, it is
            persisted into normalized_record.payload.profile + metadata.
            None for JSON ingestion path (profile_detect doesn't fire on
            free-form JSON in B2 scope).
    """
    return run_normalize_record(
        ctx, version, raw_payload, profile_dict=profile_dict
    )


def _run_ingest_validate(
    job: models.Job,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    pipeline_type: PipelineType,
    *,
    registry: IngestValidateRegistry | None = None,
) -> None:
    """Platform-level ingest validation: MIME whitelist, file size, extension whitelist.

    Reads from `ingest_validate.json` via IngestValidateRegistry. On failure,
    marks the job FAILED, writes INGEST_VALIDATE_FAILED audit, and raises
    NonRetryableError. On success, writes INGEST_VALIDATE_COMPLETED.

    If the registry is not initialized (e.g. in unit tests without lifespan),
    only the success audit is written — platform-level checks are skipped.
    Production startup loads the registry via the nexus-api lifespan.
    """
    reg = registry or get_ingest_validate_registry()
    try:
        config = reg.get_config()
    except RuntimeError:
        logger.debug(
            "ingest_validate registry not initialized; skipping platform-level checks"
        )
        write_audit(
            session,
            AuditEventType.INGEST_VALIDATE_COMPLETED,
            "raw_object",
            raw_object.id,
            trace_id,
            {
                "pipeline_type": pipeline_type.value,
                "job_id": job.id,
                "platform_checks": "skipped",
            },
        )
        return

    violations: list[dict[str, Any]] = []

    mime = (raw_object.mime_type or "").lower()
    mime_whitelist = {m.lower() for m in config.mime_whitelist}
    if mime_whitelist and mime not in mime_whitelist:
        violations.append({"check": "mime_whitelist", "value": raw_object.mime_type})

    size = raw_object.size_bytes or 0
    if size > config.file_size_max_bytes:
        violations.append(
            {"check": "file_size_max_bytes", "value": size, "limit": config.file_size_max_bytes}
        )

    filename = str(raw_object.metadata_summary.get("filename", "") or "")
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    extension_whitelist = {e.lower() for e in config.extension_whitelist}
    # Skip extension check when filename has no extension (e.g. crawler payloads without filenames).
    if ext and extension_whitelist and ext not in extension_whitelist:
        violations.append({"check": "extension_whitelist", "value": ext})

    if violations:
        reason = (
            "ingest_validate rejected raw_object: "
            + json.dumps(violations, ensure_ascii=False)
        )
        job.status = JobStatus.FAILED
        job.failure_reason = reason[:2000]
        job.last_error_code = "invalid_ingest_payload"
        job.last_error_message = reason[:2000]
        _release_lock(job)
        write_audit(
            session,
            AuditEventType.INGEST_VALIDATE_FAILED,
            "raw_object",
            raw_object.id,
            trace_id,
            {
                "pipeline_type": pipeline_type.value,
                "job_id": job.id,
                "violations": violations,
                "rules_etag": reg.get_etag(),
            },
        )
        _maybe_aggregate_batch(session, job)
        session.commit()
        raise NonRetryableError(
            reason,
            error_code="invalid_ingest_payload",
        )

    write_audit(
        session,
        AuditEventType.INGEST_VALIDATE_COMPLETED,
        "raw_object",
        raw_object.id,
        trace_id,
        {
            "pipeline_type": pipeline_type.value,
            "job_id": job.id,
            "rules_etag": reg.get_etag(),
        },
    )


def _load_record_payload(
    job: models.Job,
    raw_object: models.RawObject,
    storage: ObjectStorage,
    session: Session,
    trace_id: str | None,
) -> dict[str, Any]:
    """Load and validate the JSON payload for Pipeline B. Raises NonRetryableError on failure."""
    raw_uri = raw_object.object_uri
    raw_key = raw_uri.split("/", 3)[-1] if raw_uri.startswith("s3://") else raw_uri
    try:
        raw_bytes = storage.get_bytes(raw_key)
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        reason = f"invalid_record_payload: {type(exc).__name__}: {exc}"
        job.status = JobStatus.FAILED
        job.failure_reason = reason[:2000]
        job.last_error_code = "invalid_record_payload"
        job.last_error_message = reason[:2000]
        _release_lock(job)
        write_audit(
            session,
            AuditEventType.PIPELINE_FAILED,
            "job",
            job.id,
            trace_id,
            {"error_code": "invalid_record_payload", "reason": f"{type(exc).__name__}: {exc}"[:500]},
        )
        _maybe_aggregate_batch(session, job)
        session.commit()
        raise NonRetryableError(
            f"record pipeline payload decode failed: {type(exc).__name__}: {exc}",
            error_code="invalid_record_payload",
        )

    if not isinstance(payload, dict) or not payload:
        reason = "invalid_record_payload: payload must be a non-empty JSON object"
        job.status = JobStatus.FAILED
        job.failure_reason = reason[:2000]
        job.last_error_code = "invalid_record_payload"
        job.last_error_message = reason[:2000]
        _release_lock(job)
        write_audit(
            session,
            AuditEventType.PIPELINE_FAILED,
            "job",
            job.id,
            trace_id,
            {"error_code": "invalid_record_payload", "reason": "payload must be a non-empty JSON object"},
        )
        _maybe_aggregate_batch(session, job)
        session.commit()
        raise NonRetryableError(
            "record pipeline payload must be a non-empty JSON object",
            error_code="invalid_record_payload",
        )

    return payload


def _resolve_raw_key(raw_object: models.RawObject) -> str:
    """Strip the s3:// scheme from a raw_object's object_uri for storage lookups.

    Mirrors the inline logic in `_load_record_payload` so both record-pipeline
    inputs (JSON via `_load_record_payload` and xlsx via
    `_run_structured_parse_xlsx`) share one URI-resolution rule.
    """
    raw_uri = raw_object.object_uri
    return raw_uri.split("/", 3)[-1] if raw_uri.startswith("s3://") else raw_uri


def _fail_structured_parse(
    job: models.Job,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    *,
    error_code: str,
    reason: str,
    stage_started_at,
) -> NonRetryableError:
    """Mark the job failed for a structured_parse error.

    Writes both a `JobStage(stage_name="structured_parse", FAILED)` row and a
    PIPELINE_FAILED audit event with `error_code` so operators can disjoin
    structured_parse failures from other pipeline failures via the structured
    error code (B1.3 deliberately does NOT introduce a separate audit event
    for the failure path — failures are already uniformly tracked via
    PIPELINE_FAILED).
    """
    job.status = JobStatus.FAILED
    job.failure_reason = reason[:2000]
    job.last_error_code = error_code
    job.last_error_message = reason[:2000]
    job.current_stage = "structured_parse"
    _release_lock(job)
    stage = models.JobStage(
        job_id=job.id,
        stage_name="structured_parse",
        status=StageStatus.FAILED,
        started_at=stage_started_at,
        finished_at=utcnow(),
        failure_reason=reason[:2000],
        detail={"error_code": error_code},
    )
    session.add(stage)
    write_audit(
        session,
        AuditEventType.PIPELINE_FAILED,
        "job",
        job.id,
        trace_id,
        {
            "error_code": error_code,
            "reason": reason[:500],
            "stage": "structured_parse",
            "raw_object_id": raw_object.id,
        },
    )
    _maybe_aggregate_batch(session, job)
    session.commit()
    return NonRetryableError(reason, error_code=error_code)


def _run_structured_parse(
    job: models.Job,
    raw_object: models.RawObject,
    storage: ObjectStorage,
    session: Session,
    trace_id: str | None,
    *,
    parser_label: str,
    parser_fn,
) -> dict[str, Any]:
    """Read raw bytes, run a structured_parse parser, persist stage + audit.

    Shared core of `_run_structured_parse_xlsx` / `_run_structured_parse_csv`.
    All format-specific parsers expose the same signature
    (``source`` positional + ``source_filename`` / ``source_mime_type`` kwargs)
    and return a `ParsedWorkbook`, so the runner doesn't need format-specific
    knowledge beyond a label for error messages.

    On parser failure: emits PIPELINE_FAILED audit with a `structured_parse_*`
    error_code and raises NonRetryableError. The job will not be retried —
    corrupted structured sources are permanent faults per design §3.4.
    """
    stage_started_at = utcnow()
    raw_key = _resolve_raw_key(raw_object)

    try:
        raw_bytes = storage.get_bytes(raw_key)
    except Exception as exc:  # storage layer (S3 / MinIO) read failure
        raise _fail_structured_parse(
            job, raw_object, session, trace_id,
            error_code="structured_parse_storage_read_failed",
            reason=f"failed to read {parser_label} bytes from storage: {type(exc).__name__}: {exc}",
            stage_started_at=stage_started_at,
        ) from exc

    try:
        workbook = parser_fn(
            raw_bytes,
            source_filename=str(raw_object.metadata_summary.get("filename") or "") or None,
            source_mime_type=raw_object.mime_type,
        )
    except CorruptSourceError as exc:
        raise _fail_structured_parse(
            job, raw_object, session, trace_id,
            error_code="structured_parse_corrupt_source",
            reason=f"{parser_label} parse failed (corrupt source): {exc}",
            stage_started_at=stage_started_at,
        ) from exc
    except StructuredParseError as exc:
        raise _fail_structured_parse(
            job, raw_object, session, trace_id,
            error_code="structured_parse_failed",
            reason=f"{parser_label} parse failed: {exc}",
            stage_started_at=stage_started_at,
        ) from exc
    except Exception as exc:  # defensive: never let an unexpected parser error escape
        raise _fail_structured_parse(
            job, raw_object, session, trace_id,
            error_code="structured_parse_unexpected_error",
            reason=f"unexpected {parser_label} parser error: {type(exc).__name__}: {exc}",
            stage_started_at=stage_started_at,
        ) from exc

    sheet_summary = [
        {
            "name": s.name,
            "sheet_index": s.sheet_index,
            "row_count": s.row_count,
            "column_count": s.column_count,
            "merged_ranges_count": len(s.merged_ranges),
            "dropped_index_columns": s.dropped_index_columns,
        }
        for s in workbook.sheets
    ]

    session.add(
        models.JobStage(
            job_id=job.id,
            stage_name="structured_parse",
            status=StageStatus.SUCCEEDED,
            started_at=stage_started_at,
            finished_at=utcnow(),
            detail={
                "parser_version": workbook.parser_version,
                "format": parser_label,
                "sheet_count": len(workbook.sheets),
                "sheets": sheet_summary,
            },
        )
    )
    job.current_stage = "structured_parse"
    write_audit(
        session,
        AuditEventType.STRUCTURED_PARSE_COMPLETED,
        "raw_object",
        raw_object.id,
        trace_id,
        {
            "parser_version": workbook.parser_version,
            "format": parser_label,
            "sheet_count": len(workbook.sheets),
            "sheets": sheet_summary,
            "job_id": job.id,
            "timezone": workbook.timezone,
        },
    )
    session.flush()

    # mode="json" so datetimes etc. become strings — required for the dict
    # to flow through MinIO / governance / RAGFlow paths that JSON-serialise.
    return workbook.model_dump(mode="json")


def _run_structured_parse_xlsx(
    job: models.Job,
    raw_object: models.RawObject,
    storage: ObjectStorage,
    session: Session,
    trace_id: str | None,
) -> dict[str, Any]:
    """xlsx → ParsedWorkbook → JSON dict (B1.3)."""
    return _run_structured_parse(
        job, raw_object, storage, session, trace_id,
        parser_label="xlsx", parser_fn=parse_xlsx,
    )


def _run_structured_parse_csv(
    job: models.Job,
    raw_object: models.RawObject,
    storage: ObjectStorage,
    session: Session,
    trace_id: str | None,
) -> dict[str, Any]:
    """csv → ParsedWorkbook → JSON dict (B1.4)."""
    return _run_structured_parse(
        job, raw_object, storage, session, trace_id,
        parser_label="csv", parser_fn=parse_csv,
    )


# ---------------------------------------------------------------------------
# Pipeline B profile_detect (B2.3)
# ---------------------------------------------------------------------------

# record_types whose detection confidence is treated as "needs human review"
# even after a successful detect() call. These map exactly to the dispatcher's
# downgrade behavior in `profile_detect.detector` — keeping the list co-located
# here so any future record_type added to the catalog has to be classified by
# the worker integrator (not silently fall through).
_REVIEW_REQUIRED_RECORD_TYPES: frozenset[str] = frozenset({
    "job_demand_dataset_candidate",
    "major_distribution_dataset_candidate",
    "occupational_ability_analysis_candidate",
    "generic_table_dataset",
})


def _profile_detect_audit_summary(
    profile: ProfileDetectResult,
    *,
    job_id: str,
    raw_object_id: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "record_type": profile.record_type,
        "domain_profile": profile.domain_profile,
        "detector_version": profile.detector_version,
        "confidence": profile.confidence,
        "job_id": job_id,
    }
    if profile.analysis_model is not None:
        summary["analysis_model"] = profile.analysis_model
    if raw_object_id is not None:
        summary["raw_object_id"] = raw_object_id
    return summary


def _run_profile_detect(
    job: models.Job,
    raw_payload: dict[str, Any],
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
) -> ProfileDetectResult:
    """Reconstruct the ParsedWorkbook from raw_payload and run profile_detect.

    Runs after `_run_structured_parse_*` (which produced raw_payload via
    `workbook.model_dump(mode='json')`). Always returns a result — the
    detector itself never raises (worst case is `generic_table_dataset` at
    low confidence). On any other failure we still must not break the worker,
    so we fall back to a `generic_table_dataset` placeholder so the version
    can be parked in review_required cleanly.
    """
    try:
        workbook = ParsedWorkbook.model_validate(raw_payload)
        result = detect(workbook)
    except Exception:  # noqa: BLE001  defensive — detector contract is no-raise
        logger.exception(
            "profile_detect failed unexpectedly for job=%s; falling back to generic_table",
            job.id,
        )
        # Emit a minimal generic_table result so the rest of the pipeline
        # can record a review_required version + audit, instead of crashing
        # and leaving the asset in PROCESSING limbo.
        from nexus_app.profile_detect import DETECTOR_VERSION, ProfileEvidence
        result = ProfileDetectResult(
            record_type="generic_table_dataset",
            domain="occupation",
            domain_profile="generic_table.v1",
            detector_version=DETECTOR_VERSION,
            confidence=0.0,
            evidence=ProfileEvidence(
                sheet_names=[s.get("name", "") for s in raw_payload.get("sheets", [])],
            ),
        )

    write_audit(
        session,
        AuditEventType.RECORD_PROFILE_DETECTED,
        "raw_object",
        raw_object.id,
        trace_id,
        _profile_detect_audit_summary(result, job_id=job.id),
    )
    return result


def _maybe_park_in_review_required(
    profile: ProfileDetectResult,
    version: models.AssetVersion,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
    *,
    threshold: float = DEFAULT_AUTO_ADMIT_THRESHOLD,
) -> bool:
    """Transition version_status to REVIEW_REQUIRED when profile flags it.

    Triggers:
      - record_type is a `_candidate` / `generic_table_dataset` variant
      - confidence < threshold (defence-in-depth — the detector already
        downgrades to candidate at this point, but we double-check so a
        custom-threshold caller can't accidentally promote a low-confidence
        canonical result)

    Returns True when a transition happened (so callers can sync the
    in-memory state). Writes BOTH a VERSION_STATUS_CHANGED and a
    RECORD_PROFILE_REVIEW_REQUIRED audit so reviewers can disjoin on either.
    """
    needs_review = (
        profile.record_type in _REVIEW_REQUIRED_RECORD_TYPES
        or profile.confidence < threshold
    )
    if not needs_review:
        return False

    previous_status = version.version_status
    if previous_status != AssetVersionStatus.REVIEW_REQUIRED:
        version.version_status = AssetVersionStatus.REVIEW_REQUIRED
        write_audit(
            session,
            AuditEventType.VERSION_STATUS_CHANGED,
            "asset_version",
            version.id,
            trace_id,
            {
                "previous_status": previous_status.value,
                "current_status": AssetVersionStatus.REVIEW_REQUIRED.value,
                "reason": "profile_detect_candidate_or_low_confidence",
                "job_id": job_id,
            },
        )

    write_audit(
        session,
        AuditEventType.RECORD_PROFILE_REVIEW_REQUIRED,
        "asset_version",
        version.id,
        trace_id,
        _profile_detect_audit_summary(
            profile, job_id=job_id, raw_object_id=raw_object.id
        ),
    )
    return True


def _run_domain_normalize(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
) -> None:
    """Run the B4 / B6 domain_normalize stage and write audit.

    Lazy-imports the dispatcher so circular-import / first-touch cost is paid
    only when the stage actually runs. Failures here are audited as
    `DOMAIN_NORMALIZE_FAILED` but **swallowed** — governance can still act on
    `normalized_ref`, and the writer-specific failure already carries enough
    detail in the audit for operators to triage.
    """
    from nexus_app.domain_normalize import dispatch_domain_normalize

    try:
        result = dispatch_domain_normalize(
            session, normalized_ref, storage=ctx.storage, settings=ctx.settings
        )
    except Exception as exc:  # noqa: BLE001 — surface as audit, not failure
        logger.exception(
            "domain_normalize dispatch failed for normalized_ref=%s",
            normalized_ref.id,
        )
        write_audit(
            session,
            AuditEventType.DOMAIN_NORMALIZE_FAILED,
            "normalized_asset_ref",
            normalized_ref.id,
            trace_id,
            {
                "raw_object_id": raw_object.id,
                "job_id": job_id,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return

    write_audit(
        session,
        AuditEventType.DOMAIN_NORMALIZE_COMPLETED,
        "normalized_asset_ref",
        normalized_ref.id,
        trace_id,
        {
            "raw_object_id": raw_object.id,
            "job_id": job_id,
            "domain_profile": result.domain_profile,
            "skipped": result.skipped,
            "reason": result.reason,
            "dataset_id": result.dataset_id,
            "analysis_id": result.analysis_id,
            "records_written": result.records_written,
            "items_written": result.items_written,
        },
    )

    # B5.3 — render body_markdown derivative view. Runs on every successful
    # writer dispatch (job_demand + ability_analysis); skipped on dispatcher
    # skip. Mutates `normalized_ref.object_uri` payload in place + updates
    # ref.checksum. Failures fall back to deterministic template — never
    # raises, so the rest of the pipeline keeps moving.
    if not result.skipped and result.domain_profile in {
        "job_demand.v1", "ability_analysis.pgsd.v1"
    }:
        _run_body_markdown_render(
            ctx, normalized_ref, raw_object, session, trace_id, job_id,
            domain_profile=result.domain_profile,
        )

    # B5.2 — knowledge_unit extraction on the job_demand path. Skipped when
    # the dispatcher itself was skipped (no dataset to extract from) or when
    # the domain isn't job_demand. Failures inside the extraction service
    # are audited but never raised, so governance / chunking still get a
    # chance to run.
    if (
        not result.skipped
        and result.domain_profile == "job_demand.v1"
        and result.dataset_id is not None
    ):
        _run_requirement_extraction(
            ctx, normalized_ref, raw_object, session, trace_id, job_id,
            dataset_id=result.dataset_id,
        )

    # B5.4 — task_description_structured LLM fill on the ability_analysis
    # path. B6 always writes `{}` as a placeholder; we replace it here when
    # LLM is available. Failures audited but never raised.
    if (
        not result.skipped
        and result.domain_profile == "ability_analysis.pgsd.v1"
        and result.analysis_id is not None
    ):
        _run_task_structuring(
            ctx, normalized_ref, raw_object, session, trace_id, job_id,
            analysis_id=result.analysis_id,
        )

    # B7 — PGSD rule-engine governance on the ability_analysis path. Runs
    # AFTER B5.3 markdown render + B5.4 structuring so the version's
    # metadata_summary captures the structured task data when present.
    # Blocking findings park the version in review_required; warnings (e.g.
    # cross_sheet_inconsistency per §10.2 loose mode) are flagged-only.
    if (
        not result.skipped
        and result.domain_profile == "ability_analysis.pgsd.v1"
        and result.analysis_id is not None
    ):
        _run_ability_governance(
            ctx, normalized_ref, raw_object, session, trace_id, job_id,
            analysis_id=result.analysis_id,
        )

    # B8 — materialise the domain graph after B5 extraction. Job-demand
    # construction remains useful even if extraction was skipped: it preserves
    # the JobRole -> JobDemandRecord projection, while accepted requirement
    # items add the capability nodes when available.
    if not result.skipped and result.domain_profile in {
        "job_demand.v1", "ability_analysis.pgsd.v1"
    }:
        build_type = (
            "job_demand"
            if result.domain_profile == "job_demand.v1"
            else "ability_analysis"
        )
        _run_capability_graph_staging(
            ctx, normalized_ref, raw_object, session, trace_id, job_id,
            build_type=build_type,
        )


def _run_major_profile_normalize(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
) -> None:
    """Run Pipeline A major_profile domain-table writer when detected."""
    if normalized_ref.normalized_type != NormalizedType.DOCUMENT:
        return
    if (normalized_ref.metadata_summary or {}).get("domain_profile") != "major_profile.v1":
        return

    from nexus_app.major_profile import writer

    # The source normalized payload resides in object storage. Publish the
    # preceding normalize writes before fetching it.
    session.commit()
    try:
        uri = normalized_ref.object_uri
        key = uri.split("/", 3)[-1] if uri.startswith("s3://") else uri
        payload = json.loads(ctx.storage.get_bytes(key).decode("utf-8"))
        profile_payload = payload.get("major_profile") if isinstance(payload, dict) else None
        profiles = writer.write_many(session, normalized_ref, profile_payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "major_profile domain write failed for normalized_ref=%s",
            normalized_ref.id,
        )
        write_audit(
            session,
            AuditEventType.DOMAIN_NORMALIZE_FAILED,
            "normalized_asset_ref",
            normalized_ref.id,
            trace_id,
            {
                "raw_object_id": raw_object.id,
                "job_id": job_id,
                "domain_profile": "major_profile.v1",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return

    write_audit(
        session,
        AuditEventType.DOMAIN_NORMALIZE_COMPLETED,
        "normalized_asset_ref",
        normalized_ref.id,
        trace_id,
        {
            "raw_object_id": raw_object.id,
            "job_id": job_id,
            "domain_profile": "major_profile.v1",
            "skipped": not profiles,
            "reason": None if profiles else "major_profile_payload_missing_or_invalid",
            "profile_id": profiles[0].id if profiles else None,
            "profile_ids": [profile.id for profile in profiles],
            "records_written": len(profiles),
        },
    )


def _run_teaching_standard_graph(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
) -> None:
    """Materialize the table-backed teaching-standard capability graph."""
    session.commit()
    try:
        key = normalized_ref.object_uri.split("/", 3)[-1] if normalized_ref.object_uri.startswith("s3://") else normalized_ref.object_uri
        payload = json.loads(ctx.storage.get_bytes(key).decode("utf-8"))
        graph_payload = payload.get("teaching_standard") if isinstance(payload, dict) else None
        if not isinstance(graph_payload, dict):
            return
        from nexus_app.capability_graph import build_capability_staging
        result = build_capability_staging(
            session, normalized_ref, build_type="teaching_standard",
            domain="education", teaching_standard_payload=graph_payload,
        )
        write_audit(session, AuditEventType.CAPABILITY_GRAPH_STAGING_GENERATED,
            "normalized_asset_ref", normalized_ref.id, trace_id,
            {"raw_object_id": raw_object.id, "job_id": job_id,
             "build_type": "teaching_standard", "build_id": result.build_id,
             "skipped": result.skipped, "skipped_reason": result.skipped_reason,
             "nodes_written": result.nodes_written, "edges_written": result.edges_written,
             "quality_summary": result.quality_summary})
    except Exception:
        logger.exception("teaching_standard capability graph failed for normalized_ref=%s", normalized_ref.id)


def _run_body_markdown_render(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
    *,
    domain_profile: str,
) -> None:
    """B5.3 — render body_markdown into the existing normalized payload.

    The render pipeline (LLM → skeleton validate → deterministic fallback)
    is encapsulated in `body_markdown.render_body_markdown`. This wrapper
    handles the IO:
    - Fetch existing payload from MinIO
    - Mutate payload.body_markdown + payload.body_markdown_meta
    - Re-upload to the same object_uri (overwrite)
    - Update normalized_ref.checksum to match the new content
    - Audit the render outcome
    """
    from nexus_app.body_markdown import render_body_markdown
    from nexus_app.storage import checksum_value

    object_uri = normalized_ref.object_uri or ""
    if not object_uri:
        logger.warning(
            "body_markdown: normalized_ref %s has no object_uri; skipping",
            normalized_ref.id,
        )
        return
    key = object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri

    # Domain writers may have just flushed rows. Object storage and the
    # optional renderer LLM are both external work, so publish those writes
    # before beginning either operation.
    session.commit()

    try:
        raw = ctx.storage.get_bytes(key)
    except Exception:  # noqa: BLE001 — IO failures audited, not raised
        logger.exception(
            "body_markdown: payload fetch failed at %s; skipping", object_uri,
        )
        write_audit(
            session, AuditEventType.BODY_MARKDOWN_RENDERED,
            "normalized_asset_ref", normalized_ref.id, trace_id,
            {"job_id": job_id, "skipped": True,
             "skipped_reason": "payload_fetch_failed",
             "domain_profile": domain_profile},
        )
        return

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            "body_markdown: payload at %s is not valid JSON; skipping",
            object_uri,
        )
        write_audit(
            session, AuditEventType.BODY_MARKDOWN_RENDERED,
            "normalized_asset_ref", normalized_ref.id, trace_id,
            {"job_id": job_id, "skipped": True,
             "skipped_reason": "payload_not_json",
             "domain_profile": domain_profile},
        )
        return

    record_body = payload.get("record_body") if isinstance(payload, dict) else None
    if not isinstance(record_body, dict) or not record_body:
        write_audit(
            session, AuditEventType.BODY_MARKDOWN_RENDERED,
            "normalized_asset_ref", normalized_ref.id, trace_id,
            {"job_id": job_id, "skipped": True,
             "skipped_reason": "empty_record_body",
             "domain_profile": domain_profile},
        )
        return

    llm_client = _build_extraction_llm_client(ctx.settings)
    try:
        render_result = render_body_markdown(
            session,
            domain_profile=domain_profile,
            record_body=record_body,
            llm_client=llm_client,
        )
    except Exception as exc:  # noqa: BLE001 — render failure audited only
        logger.exception(
            "body_markdown: render failed for normalized_ref=%s",
            normalized_ref.id,
        )
        write_audit(
            session, AuditEventType.BODY_MARKDOWN_RENDERED,
            "normalized_asset_ref", normalized_ref.id, trace_id,
            {"job_id": job_id, "skipped": True,
             "skipped_reason": f"unexpected_error:{type(exc).__name__}",
             "domain_profile": domain_profile},
        )
        return

    if render_result.skipped or render_result.body_markdown is None or render_result.meta is None:
        write_audit(
            session, AuditEventType.BODY_MARKDOWN_RENDERED,
            "normalized_asset_ref", normalized_ref.id, trace_id,
            {"job_id": job_id, "skipped": True,
             "skipped_reason": render_result.skipped_reason,
             "domain_profile": domain_profile},
        )
        return

    payload["body_markdown"] = render_result.body_markdown
    payload["body_markdown_meta"] = render_result.meta.to_dict()
    new_content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        ctx.storage.put_bytes(key, new_content, "application/json", None)
    except Exception:  # noqa: BLE001 — write failure audited; don't fail pipeline
        logger.exception(
            "body_markdown: payload re-upload failed for %s", object_uri,
        )
        write_audit(
            session, AuditEventType.BODY_MARKDOWN_RENDERED,
            "normalized_asset_ref", normalized_ref.id, trace_id,
            {"job_id": job_id, "skipped": True,
             "skipped_reason": "payload_reupload_failed",
             "domain_profile": domain_profile},
        )
        return
    normalized_ref.checksum = checksum_value(new_content)

    meta_dict = render_result.meta.to_dict()
    write_audit(
        session, AuditEventType.BODY_MARKDOWN_RENDERED,
        "normalized_asset_ref", normalized_ref.id, trace_id,
        {
            "job_id": job_id,
            "raw_object_id": raw_object.id,
            "domain_profile": domain_profile,
            "render_strategy": meta_dict["render_strategy"],
            "render_scenario": meta_dict["render_scenario"],
            "render_prompt_template_id": meta_dict["render_prompt_template_id"],
            "render_rules_version_id": meta_dict["render_rules_version_id"],
            "render_confidence": meta_dict["render_confidence"],
            "render_latency_ms": meta_dict["render_latency_ms"],
            "skeleton_passed": meta_dict["skeleton_validation"]["passed"],
            "skeleton_violations": meta_dict["skeleton_validation"]["violations"],
            "fallback_reason": meta_dict["fallback_reason"],
            "record_body_hash": meta_dict["record_body_hash"],
        },
    )


def _run_requirement_extraction(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
    *,
    dataset_id: str,
) -> None:
    """B5.2 — run LLM extraction over the freshly-persisted job_demand_dataset.

    Lives next to `_run_domain_normalize` so the timing relationship
    (extraction immediately follows the writer) is obvious to readers
    grep-ing for the audit chain. LLM client is built per-call from the
    same factory the normalize service uses, so LiteLLM config / fakes /
    timeouts stay consistent across stages.
    """
    from nexus_app.knowledge_extraction import extract_requirements_for_dataset

    dataset = session.get(models.JobDemandDataset, dataset_id)
    if dataset is None:
        # Defensive: the writer just inserted this row inside the same
        # session — losing it would mean a programming error upstream.
        logger.warning(
            "knowledge_extraction: dataset %s vanished between writer and "
            "extraction; skipping (job=%s)",
            dataset_id, job_id,
        )
        return

    llm_client = _build_extraction_llm_client(ctx.settings)
    try:
        result = extract_requirements_for_dataset(
            session,
            dataset,
            llm_client=llm_client,
            max_workers=ctx.settings.worker_max_concurrent,
        )
    except Exception as exc:  # noqa: BLE001 — extraction failure never blocks pipeline
        logger.exception(
            "knowledge_extraction failed for dataset=%s", dataset_id,
        )
        write_audit(
            session,
            AuditEventType.REQUIREMENT_ITEMS_EXTRACTED,
            "job_demand_dataset",
            dataset_id,
            trace_id,
            {
                "raw_object_id": raw_object.id,
                "job_id": job_id,
                "normalized_ref_id": normalized_ref.id,
                "skipped": True,
                "skipped_reason": f"unexpected_error:{type(exc).__name__}",
            },
        )
        return

    write_audit(
        session,
        AuditEventType.REQUIREMENT_ITEMS_EXTRACTED,
        "job_demand_dataset",
        dataset_id,
        trace_id,
        {
            "raw_object_id": raw_object.id,
            "job_id": job_id,
            "normalized_ref_id": normalized_ref.id,
            "skipped": result.skipped,
            "skipped_reason": result.skipped_reason,
            "rule_set_id": result.rule_set_id,
            "prompt_profile_id": result.prompt_profile_id,
            "records_processed": result.records_processed,
            "items_persisted": result.items_persisted,
            "items_low_confidence": result.items_low_confidence,
            "items_rejected": result.items_rejected,
            "quality_summary": result.quality_summary,
        },
    )


def _run_task_structuring(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
    *,
    analysis_id: str,
) -> None:
    """B5.4 — fill task_description_structured on every task in the analysis.

    Sibling helper to `_run_requirement_extraction`. Same defensive shape:
    fetch the parent row (defending against the race where it was just
    deleted), invoke the service with a per-call LLM client, audit the
    outcome, never raise.
    """
    from nexus_app.knowledge_extraction import (
        structure_task_descriptions_for_analysis,
    )

    analysis = session.get(models.OccupationalAbilityAnalysis, analysis_id)
    if analysis is None:
        logger.warning(
            "task_structuring: analysis %s vanished between writer and "
            "structuring; skipping (job=%s)",
            analysis_id, job_id,
        )
        return

    llm_client = _build_extraction_llm_client(ctx.settings)
    try:
        result = structure_task_descriptions_for_analysis(
            session, analysis, llm_client=llm_client,
        )
    except Exception as exc:  # noqa: BLE001 — structuring failure never blocks pipeline
        logger.exception(
            "task_structuring failed for analysis=%s", analysis_id,
        )
        write_audit(
            session,
            AuditEventType.TASK_DESCRIPTIONS_STRUCTURED,
            "occupational_ability_analysis",
            analysis_id,
            trace_id,
            {
                "raw_object_id": raw_object.id,
                "job_id": job_id,
                "normalized_ref_id": normalized_ref.id,
                "skipped": True,
                "skipped_reason": f"unexpected_error:{type(exc).__name__}",
            },
        )
        return

    write_audit(
        session,
        AuditEventType.TASK_DESCRIPTIONS_STRUCTURED,
        "occupational_ability_analysis",
        analysis_id,
        trace_id,
        {
            "raw_object_id": raw_object.id,
            "job_id": job_id,
            "normalized_ref_id": normalized_ref.id,
            "skipped": result.skipped,
            "skipped_reason": result.skipped_reason,
            "rule_set_id": result.rule_set_id,
            "prompt_profile_id": result.prompt_profile_id,
            "tasks_processed": result.tasks_processed,
            "tasks_structured": result.tasks_structured,
            "tasks_rejected": result.tasks_rejected,
            "quality_summary": result.quality_summary,
        },
    )


def _run_ability_governance(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
    *,
    analysis_id: str,
) -> None:
    """B7 — rule-engine governance for ability_analysis.

    Runs the 10 §10.2 rules over the persisted analysis tree, writes one
    `governance_result` row, parks the version in review_required on any
    blocking finding, and emits an `ABILITY_ANALYSIS_GOVERNED` audit event.
    Failures are audited but never raised — governance failure must not
    block the rest of the pipeline (chunking / index_submit follow).
    """
    from nexus_app.ability_governance import govern_ability_analysis
    from nexus_app.ability_governance.persistence import (
        apply_version_state,
        persist_findings,
    )

    analysis = session.get(models.OccupationalAbilityAnalysis, analysis_id)
    if analysis is None:
        logger.warning(
            "ability_governance: analysis %s vanished between writer and "
            "governance; skipping (job=%s)",
            analysis_id, job_id,
        )
        return
    version = session.get(models.AssetVersion, normalized_ref.version_id)
    if version is None:
        logger.warning(
            "ability_governance: asset_version %s missing; skipping (job=%s)",
            normalized_ref.version_id, job_id,
        )
        return

    overview_codes = _overview_work_content_codes(
        normalized_ref, ctx.storage,
    )

    try:
        findings = govern_ability_analysis(
            session, analysis, overview_work_content_codes=overview_codes,
        )
    except Exception as exc:  # noqa: BLE001 — governance failure never blocks pipeline
        logger.exception(
            "ability_governance failed for analysis=%s", analysis_id,
        )
        write_audit(
            session, AuditEventType.ABILITY_ANALYSIS_GOVERNED,
            "occupational_ability_analysis", analysis_id, trace_id,
            {
                "raw_object_id": raw_object.id,
                "job_id": job_id,
                "normalized_ref_id": normalized_ref.id,
                "skipped": True,
                "skipped_reason": f"unexpected_error:{type(exc).__name__}",
            },
        )
        return

    if findings.skipped:
        write_audit(
            session, AuditEventType.ABILITY_ANALYSIS_GOVERNED,
            "occupational_ability_analysis", analysis_id, trace_id,
            {
                "raw_object_id": raw_object.id,
                "job_id": job_id,
                "normalized_ref_id": normalized_ref.id,
                "skipped": True,
                "skipped_reason": findings.skipped_reason,
            },
        )
        return

    result = persist_findings(
        session, findings=findings, normalized_ref=normalized_ref,
    )
    state_changed = apply_version_state(
        session, findings=findings, version=version,
    )
    if state_changed:
        write_audit(
            session, AuditEventType.VERSION_STATUS_CHANGED,
            "asset_version", version.id, trace_id,
            {
                "previous_status": AssetVersionStatus.PROCESSING.value,
                "current_status": AssetVersionStatus.REVIEW_REQUIRED.value,
                "reason": "ability_governance_blocking_findings",
                "job_id": job_id,
                "governance_result_id": result.id,
            },
        )

    write_audit(
        session, AuditEventType.ABILITY_ANALYSIS_GOVERNED,
        "occupational_ability_analysis", analysis_id, trace_id,
        {
            "raw_object_id": raw_object.id,
            "job_id": job_id,
            "normalized_ref_id": normalized_ref.id,
            "governance_result_id": result.id,
            "blocking_count": len(findings.blocking_findings),
            "warning_count": len(findings.warning_findings),
            "review_required": findings.is_blocking_required,
            "quality_summary": findings.quality_summary,
            "rule_tokens_fired": sorted(findings.quality_flags.keys()),
        },
    )


def _overview_work_content_codes(
    normalized_ref: models.NormalizedAssetRef,
    storage,
) -> set[str] | None:
    """Read the overview matrix work_content code set from MinIO payload.

    Sample 2 ships an overview sheet ("典型工作任务和工作内容分析表") whose
    work_content codes drive the B7 cross-sheet consistency rule. The
    structured_parse → record_body adapter (B3.5) doesn't currently surface
    this overview (it skips non-task sheets), so for now we look for an
    explicit `record_body.analysis.overview_work_content_codes` hint —
    None means the rule short-circuits without flagging. Future B3.5
    enhancement can populate that hint to actually exercise the rule on
    live data.
    """
    if not normalized_ref.object_uri:
        return None
    key = (
        normalized_ref.object_uri.split("/", 3)[-1]
        if normalized_ref.object_uri.startswith("s3://")
        else normalized_ref.object_uri
    )
    try:
        raw = storage.get_bytes(key)
    except Exception:  # noqa: BLE001 — missing payload silences the rule
        return None
    if not raw:
        return None
    import json as _json
    try:
        payload = _json.loads(raw)
    except (TypeError, ValueError):
        return None
    record_body = payload.get("record_body") if isinstance(payload, dict) else None
    if not isinstance(record_body, dict):
        return None
    analysis_block = record_body.get("analysis") or {}
    if not isinstance(analysis_block, dict):
        return None
    codes = analysis_block.get("overview_work_content_codes")
    if isinstance(codes, list) and all(isinstance(c, str) for c in codes):
        return set(codes)
    return None


def _run_capability_graph_staging(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    raw_object: models.RawObject,
    session: Session,
    trace_id: str | None,
    job_id: str,
    *,
    build_type: str,
) -> None:
    """B8 — materialize CapabilityGraphStaging build for `normalized_ref`.

    Runs after B7 governance. Failures are audited but never raised —
    staging is a derived view, the source domain rows + governance result
    remain the authoritative state if construction fails.
    """
    from nexus_app.capability_graph import build_capability_staging

    try:
        result = build_capability_staging(
            session, normalized_ref, build_type=build_type,
        )
    except Exception as exc:  # noqa: BLE001 — staging failure never blocks pipeline
        logger.exception(
            "capability_graph_staging failed for normalized_ref=%s",
            normalized_ref.id,
        )
        write_audit(
            session,
            AuditEventType.CAPABILITY_GRAPH_STAGING_GENERATED,
            "normalized_asset_ref",
            normalized_ref.id,
            trace_id,
            {
                "raw_object_id": raw_object.id,
                "job_id": job_id,
                "build_type": build_type,
                "skipped": True,
                "skipped_reason": f"unexpected_error:{type(exc).__name__}",
            },
        )
        return

    write_audit(
        session,
        AuditEventType.CAPABILITY_GRAPH_STAGING_GENERATED,
        "normalized_asset_ref",
        normalized_ref.id,
        trace_id,
        {
            "raw_object_id": raw_object.id,
            "job_id": job_id,
            "build_type": build_type,
            "build_id": result.build_id,
            "skipped": result.skipped,
            "skipped_reason": result.skipped_reason,
            "nodes_written": result.nodes_written,
            "edges_written": result.edges_written,
            "quality_summary": result.quality_summary,
        },
    )


def _build_extraction_llm_client(settings):
    """Construct the LiteLLM client for knowledge_extraction.

    Mirrors `_build_normalize_service` — returns None when LiteLLM isn't
    configured rather than raising, so a pipeline running in an environment
    without LLM credentials (e.g. CI without secrets) just skips extraction
    instead of crashing.
    """
    try:
        from nexus_app.ai_governance.services import _create_default_litellm_client
        return _create_default_litellm_client(settings)
    except Exception as exc:  # noqa: BLE001 — defensive boot-time fallback
        logger.info(
            "knowledge_extraction: LiteLLM unavailable, extraction will be skipped: %s",
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Main job executor
# ---------------------------------------------------------------------------

def execute_job(
    job: models.Job,
    session: Session,
    storage: ObjectStorage | None = None,
    mineru: MinerUAdapter | None = None,
    settings: Settings | None = None,
    image_analyzer: ImageAnalyzer | None = None,
) -> None:
    """Execute all pipeline stages for a single job.

    Dispatch: Pipeline A (document) → assetize → parse → normalize_document
              Pipeline B (record)   → assetize → normalize_record

    After assetize succeeds, failures are persisted without rollback so that
    the partial state (asset, version) is preserved in the failed-state record.
    """
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)
    mineru = mineru or get_mineru_adapter(settings)
    if image_analyzer is None:
        image_analyzer = get_image_analyzer(settings)

    raw_object = job.raw_object
    batch = job.ingest_batch
    trace_id = job.trace_id

    if raw_object is None or batch is None:
        job.status = JobStatus.FAILED
        job.failure_reason = "missing raw_object or ingest_batch"
        job.last_error_code = "missing_references"
        _release_lock(job)
        session.commit()
        return

    # Refuse jobs whose payload schema this worker does not recognize.
    # Sends the row straight to the dead-letter state so an operator can decide
    # whether to re-ingest under the new schema (no retry — this is a permanent
    # incompatibility, not a transient fault).
    if job.payload_schema_version not in SUPPORTED_JOB_PAYLOAD_VERSIONS:
        unsupported = job.payload_schema_version
        reason = (
            f"unsupported_payload_schema_version: {unsupported!r} "
            f"(worker accepts {sorted(SUPPORTED_JOB_PAYLOAD_VERSIONS)})"
        )
        job.status = JobStatus.DEAD_LETTERED
        job.failure_reason = reason[:2000]
        job.last_error_code = "unsupported_payload_schema_version"
        job.last_error_message = reason[:2000]
        _release_lock(job)
        write_audit(
            session,
            AuditEventType.PIPELINE_FAILED,
            "job",
            job.id,
            trace_id,
            {
                "error_code": "unsupported_payload_schema_version",
                "payload_schema_version": unsupported,
                "supported": sorted(SUPPORTED_JOB_PAYLOAD_VERSIONS),
            },
        )
        session.commit()
        return

    pipeline_type = PipelineType(job.payload.get("pipeline_type", PipelineType.DOCUMENT))

    # ingest_validate stage — platform-level checks (MIME, size, extension) FIRST,
    # then for Pipeline B dispatch to a payload-loader / parser by MIME:
    #   - xlsx → structured_parse via parse_xlsx (B1.3, feature-flagged at gateway)
    #   - csv  → structured_parse via parse_csv  (B1.4, feature-flagged at gateway)
    #   - JSON → existing _load_record_payload (crawler / database / webhook /
    #     file_upload+json) — kept as-is so existing ingestion contracts stay
    #     stable; B2 profile_detect may later route file_upload+json through
    #     parse_json once table-shaped vs business-object JSON can be disambiguated.
    # Pre-assetize stages have their own failure paths (NonRetryableError +
    # session.commit) for *expected* errors. Any other exception (DB enum
    # drift, write_audit flush failure, transient DB error, etc.) used to
    # escape uncaught and leave the job orphaned in RUNNING until lease
    # expiry — that's the root cause of the lock_expired ghost-failure
    # pattern. Catch every unexpected escape, classify via _mark_job_outcome,
    # and commit so recovery_sweep doesn't have to clean up.
    raw_payload: dict[str, Any] | None = None
    profile_result: ProfileDetectResult | None = None
    try:
        _run_ingest_validate(job, raw_object, session, trace_id, pipeline_type)
        if pipeline_type == PipelineType.RECORD:
            # Record payload loading may be a slow S3/MinIO operation. The
            # ingest-validation audit is complete, so release its transaction
            # before reading the raw JSON/CSV/XLSX bytes.
            session.commit()
            mime = (raw_object.mime_type or "").lower()
            if mime in XLSX_MIME_TYPES:
                raw_payload = _run_structured_parse_xlsx(
                    job, raw_object, storage, session, trace_id
                )
            elif mime in CSV_MIME_TYPES:
                raw_payload = _run_structured_parse_csv(
                    job, raw_object, storage, session, trace_id
                )
            else:
                raw_payload = _load_record_payload(
                    job, raw_object, storage, session, trace_id
                )

            # B2.3 profile_detect — only the structured_parse branch produces a
            # ParsedWorkbook-shaped dict that the detector can consume. JSON
            # payloads from crawler / database / webhook stay on the
            # _load_record_payload contract until B2 widens its scope.
            if mime in XLSX_MIME_TYPES or mime in CSV_MIME_TYPES:
                profile_result = _run_profile_detect(
                    job, raw_payload, raw_object, session, trace_id
                )
    except (NonRetryableError, RetryableError):
        # Stage helpers already persisted FAILED + commit; just propagate.
        raise
    except Exception as exc:
        session.rollback()
        session.add(job)
        reason = f"{type(exc).__name__}: {exc}"
        failed_stage = job.current_stage or "pre_assetize"
        _add_failure_stage(session, job, failed_stage, reason)
        _mark_job_outcome(session, job, reason, trace_id, exc)
        session.commit()
        raise

    ctx = PipelineContext(
        session=session,
        storage=storage,
        settings=settings,
        mineru=mineru if pipeline_type == PipelineType.DOCUMENT else None,
        job=job,
        raw_object=raw_object,
        batch=batch,
        trace_id=trace_id,
        pipeline_type=pipeline_type,
        image_analyzer=image_analyzer if pipeline_type == PipelineType.DOCUMENT else None,
        normalize_service=_build_normalize_service(settings),
    )

    # Stage 1: assetize — failures here are rolled back (no significant partial state)
    asset: models.Asset | None = None
    version: models.AssetVersion | None = None
    try:
        asset, version = run_assetize(ctx, raw_payload)
    except Exception as exc:
        session.rollback()
        session.add(job)
        reason = f"{type(exc).__name__}: {exc}"
        _mark_job_outcome(session, job, reason, trace_id, exc)
        session.commit()
        raise

    # Stages 2+: pipeline-specific — failures are committed as failed state (no rollback)
    try:
        if pipeline_type == PipelineType.DOCUMENT:
            normalized_ref = _run_document_pipeline(ctx, version)
            _run_major_profile_normalize(
                ctx, normalized_ref, raw_object, session, trace_id, job.id
            )
        else:
            profile_dict = (
                profile_result.model_dump(mode="json", exclude_none=True)
                if profile_result else None
            )
            normalized_ref = _run_record_pipeline(
                ctx, version, raw_payload, profile_dict=profile_dict  # type: ignore[arg-type]
            )
            # Park candidate / generic / low-confidence detections in
            # review_required so reviewers see them without waiting for
            # governance_decision. High-confidence canonicals stay in
            # PROCESSING and let governance_decision drive the next state.
            if profile_result is not None:
                _maybe_park_in_review_required(
                    profile_result, version, raw_object, session, trace_id, job.id
                )

            # Stage 3.5: domain_normalize — dispatch to per-domain writer
            # (B4 job_demand_writer / B6 ability_analysis_writer). Skipped
            # quietly when no writer is registered for the domain_profile or
            # the writer module hasn't shipped yet (B4 / B6 staggered
            # rollout). Failures are audited but **do not** fail the job —
            # governance still has a usable normalized_ref to act on.
            _run_domain_normalize(
                ctx, normalized_ref, raw_object, session, trace_id, job.id
            )

        # Stage 4: governance decision (optional — skipped if no profile/rules)
        run_governance_decision(ctx, version, normalized_ref)

        if pipeline_type == PipelineType.DOCUMENT:
            _run_teaching_standard_graph(
                ctx, normalized_ref, raw_object, session, trace_id, job.id
            )

        # Stage 5a: knowledge chunking (RAG knowledge base only — skipped otherwise)
        chunks = run_knowledge_chunking(ctx, version, normalized_ref)

        # Stage 5b: submit chunks to RAGFlow (skipped if no chunks or version not available)
        run_index_submit(ctx, version, normalized_ref, chunks)

        job.status = JobStatus.SUCCEEDED
        job.current_stage = "completed"
        job.failure_reason = None
        job.last_error_code = None
        job.last_error_message = None
        raw_object.status = RawObjectStatus.RAW_PERSISTED
        asset.status = version.version_status
        _release_lock(job)
        _maybe_aggregate_batch(session, job)
        session.commit()

    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        failed_stage = ctx.job.current_stage or "unknown"

        version.version_status = AssetVersionStatus.FAILED
        version.failure_reason = reason[:2000]
        asset.status = AssetVersionStatus.FAILED
        raw_object.status = RawObjectStatus.FAILED

        _add_failure_stage(session, job, failed_stage, reason)
        _mark_job_outcome(session, job, reason, trace_id, exc)
        session.commit()
        raise
