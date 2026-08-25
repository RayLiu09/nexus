"""Job control + read-only lookups (`/jobs/*`, `/parse-artifacts`,
`/normalized-refs`, `/audit-logs`).

The cross-cutting lookups live here because they share the operator/ops
audience with `/jobs`. Per-resource detail endpoints belong with their
domain (`assets.py`, `ai_governance.py`)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params, require_idempotency_key
from nexus_api.responses import list_response, response
from nexus_app import models, pipeline, schemas as domain_schemas, services
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AssetVersionStatus, AuditEventType, JobStatus, JobType
from nexus_app.pipeline.payload_schema import JOB_PAYLOAD_SCHEMA_VERSION

router = APIRouter()


_JOB_RETRIABLE_STATUSES = {
    JobStatus.FAILED,
    JobStatus.DEAD_LETTERED,
    JobStatus.CANCELLED,
}

_JOB_IMMEDIATE_CANCEL_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.FAILED,
    JobStatus.DEAD_LETTERED,
}


@router.get("/jobs", response_model=schemas.ListResponse[domain_schemas.JobRead])
def list_jobs(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = pipeline.list_jobs(
        session, limit=pagination.limit, offset=pagination.offset
    )
    total = pipeline.count_jobs(session)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get("/jobs/{job_id}", response_model=schemas.ApiResponse[domain_schemas.JobRead])
def get_job(job_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.Job, job_id, "job"), request)


@router.get(
    "/jobs/{job_id}/stages",
    response_model=schemas.ListResponse[domain_schemas.JobStageRead],
)
def list_job_stages(job_id: str, request: Request, session: Session = Depends(get_db)):
    services.get_row(session, models.Job, job_id, "job")
    return list_response(pipeline.list_job_stages(session, job_id), request)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=schemas.ApiResponse[schemas.JobActionResult],
)
def retry_job(job_id: str, request: Request, session: Session = Depends(get_db)):
    """Reschedule a stalled job. Allowed only when the job is in `failed`,
    `dead_lettered`, or `cancelled` — running jobs already have automatic
    retry, succeeded jobs cannot meaningfully be re-run.
    """
    job = session.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    if job.status not in _JOB_RETRIABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"job is in status '{job.status.value}', only "
                f"{[s.value for s in _JOB_RETRIABLE_STATUSES]} are retriable"
            ),
        )

    previous_status = job.status.value
    previous_attempt_count = job.attempt_count

    job.status = JobStatus.QUEUED
    job.attempt_count = 0
    job.locked_by = None
    job.locked_at = None
    job.lock_expires_at = None
    job.heartbeat_at = None
    job.failure_reason = None
    job.cancel_requested_at = None
    job.next_run_at = datetime.now(timezone.utc)

    trace_id = str(getattr(request.state, "trace_id", ""))
    write_audit(
        session,
        AuditEventType.JOB_RETRIED,
        target_type="job",
        target_id=job.id,
        trace_id=trace_id,
        summary={
            "previous_status": previous_status,
            "previous_attempt_count": previous_attempt_count,
            "retry_count": job.retry_count,
        },
    )
    if job.raw_object_id is not None:
        version = session.scalars(
            select(models.AssetVersion).where(
                models.AssetVersion.raw_object_id == job.raw_object_id
            )
        ).first()
        if version is not None and version.version_status == AssetVersionStatus.FAILED:
            version.version_status = AssetVersionStatus.PROCESSING
            version.failure_reason = None
            write_audit(
                session,
                AuditEventType.VERSION_STATUS_CHANGED,
                target_type="asset_version",
                target_id=version.id,
                trace_id=trace_id,
                summary={
                    "from_status": AssetVersionStatus.FAILED.value,
                    "to_status": AssetVersionStatus.PROCESSING.value,
                    "reason": "operator_retry",
                    "job_id": job.id,
                },
            )

    session.commit()
    session.refresh(job)
    return response(
        schemas.JobActionResult(
            job_id=job.id,
            status=job.status.value,
            attempt_count=job.attempt_count,
        ),
        request,
    )


@router.post(
    "/jobs/reprocess",
    response_model=schemas.ApiResponse[schemas.JobReprocessResult],
    status_code=202,
    dependencies=[Depends(require_idempotency_key)],
)
def reprocess_asset_version(
    payload: schemas.JobReprocessRequest,
    request: Request,
    idempotency_key: str = Depends(require_idempotency_key),
    session: Session = Depends(get_db),
):
    """Queue a full replay from retained raw data as a new asset version.

    The source version and its governance evidence remain immutable. The
    normal ingest executor creates the replacement version and applies the
    current parsing, normalization and governance rules.
    """
    source_version = session.get(models.AssetVersion, payload.asset_version_id)
    if source_version is None:
        raise HTTPException(
            status_code=404,
            detail=f"asset version '{payload.asset_version_id}' not found",
        )
    raw_object = source_version.raw_object
    if raw_object is None or raw_object.batch is None:
        raise HTTPException(
            status_code=409,
            detail="asset version cannot be reprocessed because retained raw data is missing",
        )

    existing_job = session.scalar(
        select(models.Job)
        .where(
            models.Job.job_type == JobType.INGEST_PROCESS,
            models.Job.idempotency_key == idempotency_key,
        )
        .order_by(models.Job.created_at.desc())
        .limit(1)
    )
    if existing_job is not None:
        if (existing_job.metadata_summary or {}).get("reprocess_of_version_id") != source_version.id:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key was already used for a different reprocess request",
            )
        return response(
            schemas.JobReprocessResult(
                job_id=existing_job.id,
                status=existing_job.status.value,
                attempt_count=existing_job.attempt_count,
                asset_version_id=source_version.id,
                reprocess_of_version_id=source_version.id,
                idempotent=True,
            ),
            request,
        )

    source_job = session.scalar(
        select(models.Job)
        .where(
            models.Job.raw_object_id == raw_object.id,
            models.Job.job_type == JobType.INGEST_PROCESS,
        )
        .order_by(models.Job.created_at.desc())
        .limit(1)
    )
    if source_job is None:
        raise HTTPException(
            status_code=409,
            detail="asset version cannot be reprocessed because its pipeline routing payload is missing",
        )
    pipeline_type = (source_job.payload or {}).get("pipeline_type")
    if not isinstance(pipeline_type, str) or not pipeline_type:
        raise HTTPException(status_code=409, detail="source job has no pipeline_type payload")

    next_version_no = (
        session.scalar(
            select(func.max(models.AssetVersion.version_no)).where(
                models.AssetVersion.asset_id == source_version.asset_id,
            )
        )
        or 0
    ) + 1
    replacement_version = models.AssetVersion(
        asset_id=source_version.asset_id,
        raw_object_id=raw_object.id,
        version_no=next_version_no,
        version_status=AssetVersionStatus.PROCESSING,
        source_checksum=raw_object.checksum,
        metadata_summary={
            **(source_version.metadata_summary or {}),
            "m1_ready_for_governance": False,
            "reprocess_of_version_id": source_version.id,
        },
    )
    session.add(replacement_version)
    session.flush()

    trace_id = str(getattr(request.state, "trace_id", "")) or None
    job = models.Job(
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.QUEUED,
        ingest_batch_id=raw_object.batch_id,
        raw_object_id=raw_object.id,
        idempotency_key=idempotency_key,
        current_stage="queued",
        trace_id=trace_id,
        payload={
            "raw_object_id": raw_object.id,
            "batch_id": raw_object.batch_id,
            "pipeline_type": pipeline_type,
            "source_object_key": (source_job.payload or {}).get("source_object_key"),
            "operation": "reprocess",
            "reprocess_target_version_id": replacement_version.id,
        },
        payload_schema_version=JOB_PAYLOAD_SCHEMA_VERSION,
        metadata_summary={
            "pipeline": "ingest_to_asset",
            "operation": "reprocess",
            "reprocess_of_version_id": source_version.id,
            "reprocess_target_version_id": replacement_version.id,
            "reprocess_of_job_id": source_job.id,
        },
    )
    session.add(job)
    session.flush()
    write_audit(
        session,
        AuditEventType.JOB_RETRIED,
        target_type="job",
        target_id=job.id,
        trace_id=trace_id,
        summary={
            "operation": "reprocess",
            "source_asset_version_id": source_version.id,
            "replacement_asset_version_id": replacement_version.id,
            "source_job_id": source_job.id,
            "pipeline_type": pipeline_type,
        },
    )
    session.commit()
    session.refresh(job)
    return response(
        schemas.JobReprocessResult(
            job_id=job.id,
            status=job.status.value,
            attempt_count=job.attempt_count,
            asset_version_id=source_version.id,
            reprocess_of_version_id=source_version.id,
        ),
        request,
    )


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=schemas.ApiResponse[schemas.JobActionResult],
)
def cancel_job(job_id: str, request: Request, session: Session = Depends(get_db)):
    """Cancel a job.

    - `queued` / `failed` / `dead_lettered` — flipped to `cancelled` immediately.
    - `running` — sets `cancel_requested_at` so the worker can honor it at the
      next stage boundary. Status stays `running` until the worker observes
      the flag; status code 202.
    - `succeeded` / `cancelled` — 409 (terminal).
    """
    job = session.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")

    trace_id = str(getattr(request.state, "trace_id", ""))

    if job.status in _JOB_IMMEDIATE_CANCEL_STATUSES:
        previous_status = job.status.value
        job.status = JobStatus.CANCELLED
        job.cancel_requested_at = datetime.now(timezone.utc)
        job.locked_by = None
        job.lock_expires_at = None
        write_audit(
            session,
            AuditEventType.JOB_CANCELLED,
            target_type="job",
            target_id=job.id,
            trace_id=trace_id,
            summary={"previous_status": previous_status, "effective": "immediate"},
        )
        session.commit()
        session.refresh(job)
        return response(
            schemas.JobActionResult(
                job_id=job.id,
                status=job.status.value,
                cancel_requested_at=job.cancel_requested_at.isoformat(),
            ),
            request,
        )

    if job.status == JobStatus.RUNNING:
        if job.cancel_requested_at is None:
            job.cancel_requested_at = datetime.now(timezone.utc)
            write_audit(
                session,
                AuditEventType.JOB_CANCELLED,
                target_type="job",
                target_id=job.id,
                trace_id=trace_id,
                summary={
                    "previous_status": JobStatus.RUNNING.value,
                    "effective": "requested_pending_worker",
                },
            )
            session.commit()
            session.refresh(job)
        return JSONResponse(
            status_code=202,
            content=schemas.ApiResponse[schemas.JobActionResult](
                data=schemas.JobActionResult(
                    job_id=job.id,
                    status=job.status.value,
                    cancel_requested_at=job.cancel_requested_at.isoformat(),
                ),
                meta=schemas.ResponseMeta(trace_id=trace_id),
            ).model_dump(),
        )

    raise HTTPException(
        status_code=409,
        detail=f"job is in terminal status '{job.status.value}' and cannot be cancelled",
    )


# ── Cross-cutting read-only lookups ──────────────────────────────────────


@router.get(
    "/parse-artifacts",
    response_model=schemas.ListResponse[domain_schemas.ParseArtifactRead],
)
def list_parse_artifacts(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = services.list_rows(
        session, models.ParseArtifact, limit=pagination.limit, offset=pagination.offset
    )
    total = services.count_rows(session, models.ParseArtifact)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get(
    "/normalized-refs",
    response_model=schemas.ListResponse[domain_schemas.NormalizedAssetRefRead],
)
def list_normalized_refs(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = services.list_rows(
        session, models.NormalizedAssetRef, limit=pagination.limit, offset=pagination.offset
    )
    total = services.count_rows(session, models.NormalizedAssetRef)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get("/audit-logs", response_model=schemas.ListResponse[domain_schemas.AuditLogRead])
def list_audit_logs(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = services.list_rows(
        session, models.AuditLog, limit=pagination.limit, offset=pagination.offset
    )
    total = services.count_rows(session, models.AuditLog)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )
