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
from nexus_app.mineru import MinerUAdapter, get_mineru_adapter
from nexus_app.models import utcnow
from nexus_app.normalize.service import NormalizeService
from nexus_app.pipeline.context import PipelineContext
from nexus_app.pipeline.payload_schema import SUPPORTED_JOB_PAYLOAD_VERSIONS
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
        write_audit(
            session,
            AuditEventType.PIPELINE_FAILED,
            "job",
            job.id,
            trace_id,
            {"error_code": "dead_lettered", "reason": reason[:500], "attempt_count": job.attempt_count},
        )
    else:
        job.status = JobStatus.FAILED
        job.failure_reason = reason[:2000]
        job.last_error_code = error_code
        job.last_error_message = reason[:2000]
        write_audit(
            session,
            AuditEventType.PIPELINE_FAILED,
            "job",
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
) -> models.NormalizedAssetRef:
    """Pipeline B: normalize_record (no parse stage)."""
    return run_normalize_record(ctx, version, raw_payload)


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
    # then for Pipeline B also decode and validate the JSON payload structure.
    _run_ingest_validate(job, raw_object, session, trace_id, pipeline_type)
    raw_payload: dict[str, Any] | None = None
    if pipeline_type == PipelineType.RECORD:
        raw_payload = _load_record_payload(job, raw_object, storage, session, trace_id)

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
        else:
            normalized_ref = _run_record_pipeline(ctx, version, raw_payload)  # type: ignore[arg-type]

        # Stage 4: governance decision (optional — skipped if no profile/rules)
        run_governance_decision(ctx, version, normalized_ref)

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
