from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.config import Settings, get_settings
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    IngestBatchStatus,
    JobStatus,
    RawObjectStatus,
    StageStatus,
)
from nexus_app.mineru import MinerUAdapter, get_mineru_adapter
from nexus_app.models import utcnow
from nexus_app.pipeline.context import PipelineContext
from nexus_app.pipeline.stages import run_assetize, run_normalize, run_parse
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
    if any(w in name or w in msg for w in ("timeout", "connection", "deadlock", "operationalerror")):
        return "retryable"
    return "non_retryable"


def _release_lock(job: models.Job) -> None:
    job.locked_by = None
    job.lock_expires_at = None


def _add_failure_stage(session: Session, job: models.Job, stage_name: str, reason: str) -> None:
    now = utcnow()
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


def _mark_dead_lettered(
    session: Session,
    job: models.Job,
    reason: str,
    trace_id: str | None,
) -> None:
    _release_lock(job)
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


def _mark_retry(session: Session, job: models.Job, reason: str) -> None:
    _release_lock(job)
    delay = _backoff_seconds(job.attempt_count)
    job.status = JobStatus.QUEUED
    job.next_run_at = utcnow() + timedelta(seconds=delay)
    job.failure_reason = reason[:2000]
    job.last_error_message = reason[:2000]


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


def execute_job(
    job: models.Job,
    session: Session,
    storage: ObjectStorage | None = None,
    mineru: MinerUAdapter | None = None,
    settings: Settings | None = None,
) -> None:
    """Execute all pipeline stages for a single job.

    Stage order: assetize → parse (documents only) → normalize.

    After assetize succeeds, failures are persisted without rollback so that
    the partial state (asset, version) is preserved in the failed-state record.
    """
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)
    mineru = mineru or get_mineru_adapter(settings)

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

    pipeline_type = job.payload.get("pipeline_type", "document")

    ctx = PipelineContext(
        session=session,
        storage=storage,
        settings=settings,
        mineru=mineru,
        job=job,
        raw_object=raw_object,
        batch=batch,
        trace_id=trace_id,
        pipeline_type=pipeline_type,
    )

    raw_payload: dict[str, Any] | None = None
    if pipeline_type == "record":
        raw_uri = raw_object.object_uri
        raw_key = raw_uri.split("/", 3)[-1] if raw_uri.startswith("s3://") else raw_uri
        try:
            import json
            raw_bytes = storage.get_bytes(raw_key)
            raw_payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            raw_payload = {}

    # Stage 1: assetize — failures here are rolled back (no significant partial state)
    asset: models.DocumentAsset | None = None
    version: models.DocumentVersion | None = None
    try:
        asset, version = run_assetize(ctx, raw_payload)
    except Exception as exc:
        session.rollback()
        session.add(job)
        reason = f"{type(exc).__name__}: {exc}"
        _mark_job_outcome(session, job, reason, trace_id, exc)
        session.commit()
        raise

    # Stages 2 & 3: parse + normalize — failures are committed as failed state (no rollback)
    try:
        parse_artifact = None
        if pipeline_type == "document":
            parse_artifact = run_parse(ctx, version)

        normalized_ref = run_normalize(ctx, version, parse_artifact, raw_payload)

        batch.status = IngestBatchStatus.COMPLETED
        job.status = JobStatus.SUCCEEDED
        job.current_stage = "completed"
        job.failure_reason = None
        _release_lock(job)
        session.commit()

    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        failed_stage = ctx.job.current_stage or "unknown"

        version.version_status = AssetVersionStatus.FAILED
        version.failure_reason = reason[:2000]
        asset.status = AssetVersionStatus.FAILED
        raw_object.status = RawObjectStatus.FAILED
        batch.status = IngestBatchStatus.FAILED

        _add_failure_stage(session, job, failed_stage, reason)
        _mark_job_outcome(session, job, reason, trace_id, exc)
        session.commit()
        raise
