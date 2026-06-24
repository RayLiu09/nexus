"""Multi-raw batch lifecycle (TP-W5-01 / TP-W5-02 / TP-W5-03).

Two-step API:
    1. create_batch() — create batch in `open` state with no files
    2. append_file_to_batch() — add one raw object + job (idempotent per file)

Aggregate status:
    update_batch_aggregate_status() — called by worker after each job terminal
    write to roll up job statuses into the batch.

Batch is closed to appends as soon as any job leaves `queued`. The status
machine:
    open       → batch created, accepting appends
    submitted  → first file appended
    raw_persisted → all queued raw objects persisted (transient, set on append)
    processing → at least one job running
    completed  → all jobs succeeded
    partial_failed → some succeeded, some failed
    failed     → all jobs failed/dead_lettered
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.config import Settings, get_settings
from nexus_app.enums import (
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    JobStatus,
    PipelineType,
    RawObjectStatus,
)
from nexus_app.ingest.gateway import (
    _create_queued_job,
    _pipeline_type_for,
)
from nexus_app.ingest.keys import raw_key
from nexus_app.storage import ObjectStorage, checksum_value, get_object_storage
from nexus_app.worker.notify import notify_job_ready

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

MAX_FILES_PER_BATCH: Final[int] = 100
"""Max raw objects a single open batch may hold before append is rejected."""

_OPEN_FOR_APPEND: Final[frozenset[IngestBatchStatus]] = frozenset(
    {
        IngestBatchStatus.OPEN,
        IngestBatchStatus.SUBMITTED,
        IngestBatchStatus.RAW_PERSISTED,
    }
)
"""Batch statuses that still accept file appends. Once any job is running or
terminal, the batch is closed (per TP-W5-01 implementation constraint)."""


# --------------------------------------------------------------------------- #
# Errors                                                                      #
# --------------------------------------------------------------------------- #

class BatchError(Exception):
    """Base class for batch lifecycle errors."""


class BatchNotFoundError(BatchError):
    """Raised when the requested batch_id does not exist."""


class BatchClosedError(BatchError):
    """Raised when a file is appended to a batch that no longer accepts appends."""


class BatchFullError(BatchError):
    """Raised when MAX_FILES_PER_BATCH is reached."""


class DataSourceNotFoundError(BatchError):
    """Raised when the data_source referenced by a batch is missing."""


# --------------------------------------------------------------------------- #
# Aggregation strategy (protocol + default)                                   #
# --------------------------------------------------------------------------- #

class AggregationStrategy(Protocol):
    def aggregate(self, job_statuses: list[JobStatus]) -> IngestBatchStatus: ...


class DefaultAggregationStrategy:
    """Standard aggregation per TP-W5-02 spec."""

    def aggregate(self, job_statuses: list[JobStatus]) -> IngestBatchStatus:
        return _aggregate_job_statuses(job_statuses)


def _aggregate_job_statuses(statuses: list[JobStatus]) -> IngestBatchStatus:
    """Pure aggregator: roll up a list of job statuses into a batch status.

    Rules:
      - empty list → OPEN (no files yet)
      - any QUEUED or RUNNING → PROCESSING
      - all terminal & all SUCCEEDED → COMPLETED
      - all terminal & all FAILED/DEAD_LETTERED → FAILED
      - mix of SUCCEEDED and FAILED/DEAD_LETTERED → PARTIAL_FAILED
    """
    if not statuses:
        return IngestBatchStatus.OPEN

    active = {JobStatus.QUEUED, JobStatus.RUNNING}
    if any(s in active for s in statuses):
        return IngestBatchStatus.PROCESSING

    succeeded = sum(1 for s in statuses if s == JobStatus.SUCCEEDED)
    failed_like = sum(
        1
        for s in statuses
        if s in {JobStatus.FAILED, JobStatus.DEAD_LETTERED, JobStatus.CANCELLED}
    )
    review = sum(1 for s in statuses if s == JobStatus.REVIEW_REQUIRED)

    # REVIEW_REQUIRED counts as non-failed/non-success; treat as still in-flight
    # for aggregation (job will eventually transition).
    if review:
        return IngestBatchStatus.PROCESSING

    if succeeded and not failed_like:
        return IngestBatchStatus.COMPLETED
    if failed_like and not succeeded:
        return IngestBatchStatus.FAILED
    return IngestBatchStatus.PARTIAL_FAILED


# --------------------------------------------------------------------------- #
# Batch creation                                                              #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BatchAppendResult:
    raw_object: models.RawObject
    job: models.Job
    duplicate: bool
    """True when this append returned an existing raw_object/job (idempotent replay)
    or was deduplicated against an existing checksum in the same batch."""


def create_batch(
    session: Session,
    *,
    data_source_id: str,
    batch_idempotency_key: str,
    owner_user_id: str | None = None,
    summary: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> models.IngestBatch:
    """Create or return an existing batch in `open` state.

    Idempotent on `(data_source_id, batch_idempotency_key)`.
    """
    data_source = session.get(models.DataSource, data_source_id)
    if data_source is None:
        raise DataSourceNotFoundError(f"data_source {data_source_id} not found")

    existing = session.scalar(
        select(models.IngestBatch).where(
            models.IngestBatch.data_source_id == data_source_id,
            models.IngestBatch.idempotency_key == batch_idempotency_key,
        )
    )
    if existing is not None:
        return existing

    batch = models.IngestBatch(
        data_source_id=data_source_id,
        idempotency_key=batch_idempotency_key,
        source_type=data_source.source_type,
        status=IngestBatchStatus.OPEN,
        owner_user_id=owner_user_id,
        summary=dict(summary or {}),
        batch_status_detail={},
    )
    session.add(batch)
    session.flush()

    write_audit(
        session,
        AuditEventType.INGEST_BATCH_SUBMITTED,
        "ingest_batch",
        batch.id,
        trace_id,
        {
            "idempotency_key": batch_idempotency_key,
            "data_source_id": data_source_id,
            "object_count": 0,
            "phase": "open",
        },
    )
    session.commit()
    return batch


# --------------------------------------------------------------------------- #
# File append                                                                 #
# --------------------------------------------------------------------------- #

def _ensure_batch_open(batch: models.IngestBatch) -> None:
    if batch.status not in _OPEN_FOR_APPEND:
        raise BatchClosedError(
            f"batch {batch.id} is not open for append (status={batch.status.value})"
        )


def _ensure_batch_capacity(session: Session, batch: models.IngestBatch) -> None:
    existing = session.scalars(
        select(models.RawObject.id).where(models.RawObject.batch_id == batch.id)
    ).all()
    if len(existing) >= MAX_FILES_PER_BATCH:
        raise BatchFullError(
            f"batch {batch.id} reached MAX_FILES_PER_BATCH={MAX_FILES_PER_BATCH}"
        )


def _find_existing_append(
    session: Session,
    batch_id: str,
    file_idempotency_key: str,
) -> tuple[models.RawObject, models.Job] | None:
    raw = session.scalar(
        select(models.RawObject).where(
            models.RawObject.batch_id == batch_id,
            models.RawObject.file_idempotency_key == file_idempotency_key,
        )
    )
    if raw is None:
        return None
    job = session.scalar(
        select(models.Job)
        .where(
            models.Job.ingest_batch_id == batch_id,
            models.Job.raw_object_id == raw.id,
        )
        .order_by(models.Job.created_at.desc())
    )
    return (raw, job) if job is not None else None


def _find_same_batch_checksum_dup(
    session: Session,
    batch_id: str,
    checksum: str,
) -> models.RawObject | None:
    return session.scalar(
        select(models.RawObject).where(
            models.RawObject.batch_id == batch_id,
            models.RawObject.checksum == checksum,
        )
    )


def _audit_cross_source_duplicate(
    session: Session,
    data_source_id: str,
    checksum: str,
    file_idempotency_key: str,
    trace_id: str | None,
) -> None:
    cross_dup = session.scalar(
        select(models.RawObject).where(
            models.RawObject.data_source_id != data_source_id,
            models.RawObject.checksum == checksum,
        )
    )
    if cross_dup is None:
        return
    write_audit(
        session,
        AuditEventType.CROSS_SOURCE_DUPLICATE_DETECTED,
        "raw_object",
        cross_dup.id,
        trace_id,
        {
            "incoming_data_source_id": data_source_id,
            "existing_data_source_id": cross_dup.data_source_id,
            "checksum": checksum,
            "file_idempotency_key": file_idempotency_key,
        },
    )


def _store_and_create_raw(
    *,
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    batch: models.IngestBatch,
    data_source: models.DataSource,
    file_idempotency_key: str,
    content: bytes,
    filename: str,
    mime_type: str,
    source_uri: str | None,
    checksum: str,
) -> models.RawObject:
    key = raw_key(
        settings,
        data_source.source_type,
        data_source.id,
        file_idempotency_key,
        checksum,
        filename,
    )
    stored = storage.put_bytes(
        key,
        content,
        mime_type,
        {
            "nexus-data-source-id": data_source.id,
            "nexus-batch-id": batch.id,
            "nexus-file-idempotency-key": file_idempotency_key.encode("utf-8").hex()
            if not file_idempotency_key.isascii()
            else file_idempotency_key,
        },
    )
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=data_source.source_type,
        source_uri=source_uri,
        object_uri=stored.object_uri,
        checksum=stored.checksum,
        mime_type=mime_type,
        size_bytes=stored.size_bytes,
        status=RawObjectStatus.RAW_PERSISTED,
        file_idempotency_key=file_idempotency_key,
        metadata_summary={"filename": filename},
    )
    session.add(raw)
    session.flush()
    return raw


def append_file_to_batch(
    session: Session,
    batch_id: str,
    *,
    file_idempotency_key: str,
    filename: str,
    content: bytes,
    mime_type: str,
    source_uri: str | None = None,
    source_object_key: str | None = None,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
    trace_id: str | None = None,
) -> BatchAppendResult:
    """Append a single file (raw object + job) to an open batch.

    Idempotent on `(batch_id, file_idempotency_key)`. Same-checksum duplicates
    within the batch reuse the existing raw_object and emit a SUCCEEDED job
    flagged as `duplicate_skipped`.
    """
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)

    batch = session.get(models.IngestBatch, batch_id)
    if batch is None:
        raise BatchNotFoundError(f"batch {batch_id} not found")
    _ensure_batch_open(batch)

    # 1. file-level idempotency replay
    replay = _find_existing_append(session, batch_id, file_idempotency_key)
    if replay is not None:
        existing_raw, existing_job = replay
        return BatchAppendResult(existing_raw, existing_job, duplicate=True)

    _ensure_batch_capacity(session, batch)

    data_source = session.get(models.DataSource, batch.data_source_id)
    if data_source is None:
        raise DataSourceNotFoundError(
            f"data_source {batch.data_source_id} not found for batch {batch_id}"
        )

    content_checksum = checksum_value(content)

    # 2. same-batch checksum dedup → reuse raw_object, job marked duplicate_skipped
    same_batch_dup = _find_same_batch_checksum_dup(session, batch_id, content_checksum)
    if same_batch_dup is not None:
        # Stamp the file_idempotency_key onto a fresh job that points at the
        # existing raw object so the (batch_id, file_idempotency_key) unique
        # constraint logic via Job is observable, and the caller sees a stable
        # response. We do NOT create another RawObject row.
        job = _create_queued_job(
            session,
            batch,
            same_batch_dup,
            file_idempotency_key,
            trace_id,
            pipeline_type=_pipeline_type_for(
                data_source.source_type, same_batch_dup.mime_type, settings=settings
            ).value,
            source_object_key=source_object_key or source_uri or file_idempotency_key,
        )
        job.status = JobStatus.SUCCEEDED
        job.current_stage = "duplicate_skipped"
        _update_status_detail_entry(batch, same_batch_dup.id, job.status)
        # batch may have only the dup so far → keep status as submitted
        if batch.status == IngestBatchStatus.OPEN:
            batch.status = IngestBatchStatus.SUBMITTED
        session.commit()
        return BatchAppendResult(same_batch_dup, job, duplicate=True)

    # 3. cross-source duplicate → audit only, continue
    _audit_cross_source_duplicate(
        session, data_source.id, content_checksum, file_idempotency_key, trace_id
    )

    # 4. persist raw + queue job
    raw = _store_and_create_raw(
        session=session,
        storage=storage,
        settings=settings,
        batch=batch,
        data_source=data_source,
        file_idempotency_key=file_idempotency_key,
        content=content,
        filename=filename,
        mime_type=mime_type,
        source_uri=source_uri,
        checksum=content_checksum,
    )
    pipeline_type = _pipeline_type_for(
        data_source.source_type, mime_type, settings=settings
    )
    job = _create_queued_job(
        session,
        batch,
        raw,
        file_idempotency_key,
        trace_id,
        pipeline_type=pipeline_type.value,
        source_object_key=source_object_key or source_uri or file_idempotency_key,
    )

    # 5. batch status transition: first file flips open → submitted
    if batch.status == IngestBatchStatus.OPEN:
        batch.status = IngestBatchStatus.SUBMITTED
    if batch.status == IngestBatchStatus.SUBMITTED:
        batch.status = IngestBatchStatus.RAW_PERSISTED

    _update_status_detail_entry(batch, raw.id, job.status)

    write_audit(
        session,
        AuditEventType.RAW_OBJECT_PERSISTED,
        "raw_object",
        raw.id,
        trace_id,
        {
            "batch_id": batch.id,
            "checksum": raw.checksum,
            "size_bytes": raw.size_bytes,
            "file_idempotency_key": file_idempotency_key,
        },
    )

    notify_job_ready(session)
    session.commit()
    return BatchAppendResult(raw, job, duplicate=False)


# --------------------------------------------------------------------------- #
# Aggregation                                                                 #
# --------------------------------------------------------------------------- #

def _update_status_detail_entry(
    batch: models.IngestBatch,
    raw_object_id: str,
    job_status: JobStatus,
) -> None:
    """Merge a single raw_object→job_status entry into batch_status_detail."""
    detail = dict(batch.batch_status_detail or {})
    detail[raw_object_id] = job_status.value
    batch.batch_status_detail = detail


def update_batch_aggregate_status(
    session: Session,
    batch_id: str,
    *,
    strategy: AggregationStrategy | None = None,
) -> models.IngestBatch:
    """Recompute batch.status and batch_status_detail from all jobs.

    Called by worker.runner after each job terminal write. Idempotent: running
    repeatedly with no underlying changes yields the same status.
    """
    strategy = strategy or DefaultAggregationStrategy()

    batch = session.get(models.IngestBatch, batch_id)
    if batch is None:
        raise BatchNotFoundError(f"batch {batch_id} not found")

    jobs = list(
        session.scalars(
            select(models.Job).where(models.Job.ingest_batch_id == batch_id)
        ).all()
    )
    statuses = [j.status for j in jobs]

    aggregated = strategy.aggregate(statuses)
    detail = {
        j.raw_object_id: j.status.value
        for j in jobs
        if j.raw_object_id is not None
    }
    batch.batch_status_detail = detail
    batch.status = aggregated
    session.flush()
    return batch
