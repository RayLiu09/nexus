from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    JobType,
    RawObjectStatus,
)
from nexus_app.ingest.adapter_base import IngestAdapter
from nexus_app.ingest.adapter_crawler import CrawlerPackageAdapter
from nexus_app.ingest.adapter_file import FileUploadAdapter
from nexus_app.ingest.keys import raw_key
from nexus_app.schemas import CrawlerPackageSubmit, IngestFileSubmit
from nexus_app.storage import ObjectStorage, checksum_value, get_object_storage
from nexus_app.worker.notify import notify_job_ready


@dataclass(frozen=True)
class IngestAccepted:
    batch: models.IngestBatch
    raw_object: models.RawObject
    job: models.Job


class IngestError(ValueError):
    pass


def _find_or_create_batch(
    session: Session,
    data_source_id: str,
    idempotency_key: str,
    source_type: DataSourceType,
    owner_user_id: str | None,
    summary: dict[str, Any],
) -> tuple[models.IngestBatch, bool]:
    existing = session.scalar(
        select(models.IngestBatch).where(
            models.IngestBatch.data_source_id == data_source_id,
            models.IngestBatch.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, False

    batch = models.IngestBatch(
        data_source_id=data_source_id,
        idempotency_key=idempotency_key,
        source_type=source_type,
        status=IngestBatchStatus.SUBMITTED,
        owner_user_id=owner_user_id,
        summary=summary,
    )
    session.add(batch)
    session.flush()
    return batch, True


def _create_queued_job(
    session: Session,
    batch: models.IngestBatch,
    raw_object: models.RawObject,
    idempotency_key: str,
    trace_id: str | None,
) -> models.Job:
    job = models.Job(
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.QUEUED,
        ingest_batch_id=batch.id,
        raw_object_id=raw_object.id,
        idempotency_key=idempotency_key,
        current_stage="queued",
        trace_id=trace_id,
        payload={"raw_object_id": raw_object.id, "batch_id": batch.id},
        metadata_summary={"pipeline": "ingest_to_asset"},
    )
    session.add(job)
    session.flush()
    return job


def _submit_ingest(
    session: Session,
    adapter: IngestAdapter,
    storage: ObjectStorage,
    settings: Settings,
    trace_id: str | None,
) -> IngestAccepted:
    data_source = session.get(models.DataSource, adapter.data_source_id)
    if data_source is None:
        raise IngestError("data_source not found")

    prepared = adapter.prepare()
    content_checksum = checksum_value(prepared.content)

    batch, created = _find_or_create_batch(
        session,
        adapter.data_source_id,
        adapter.idempotency_key,
        data_source.source_type,
        adapter.owner_user_id,
        prepared.batch_summary,
    )
    if not created:
        existing_raw = session.scalar(
            select(models.RawObject).where(models.RawObject.batch_id == batch.id)
        )
        existing_job = session.scalar(
            select(models.Job).where(models.Job.ingest_batch_id == batch.id)
        )
        if existing_raw is None and existing_job is not None:
            existing_raw = existing_job.raw_object
        session.commit()
        return IngestAccepted(batch, existing_raw, existing_job)

    # Same-source duplicate check (blocks re-ingestion)
    duplicate_raw = session.scalar(
        select(models.RawObject).where(
            models.RawObject.data_source_id == data_source.id,
            models.RawObject.checksum == content_checksum,
        )
    )
    if duplicate_raw is not None:
        batch.status = IngestBatchStatus.DUPLICATE_SKIPPED
        batch.summary = {**batch.summary, "duplicate_raw_object_id": duplicate_raw.id}
        job = _create_queued_job(session, batch, duplicate_raw, adapter.idempotency_key, trace_id)
        job.status = JobStatus.SUCCEEDED
        job.current_stage = "duplicate_skipped"
        write_audit(
            session,
            AuditEventType.INGEST_BATCH_SUBMITTED,
            "ingest_batch",
            batch.id,
            trace_id,
            {
                "idempotency_key": adapter.idempotency_key,
                "duplicate_raw_object_id": duplicate_raw.id,
            },
        )
        session.commit()
        return IngestAccepted(batch, duplicate_raw, job)

    # Cross-source duplicate check (audit only, does not block)
    cross_dup = session.scalar(
        select(models.RawObject).where(
            models.RawObject.data_source_id != data_source.id,
            models.RawObject.checksum == content_checksum,
        )
    )
    if cross_dup is not None:
        write_audit(
            session,
            AuditEventType.CROSS_SOURCE_DUPLICATE_DETECTED,
            "raw_object",
            cross_dup.id,
            trace_id,
            {
                "incoming_data_source_id": data_source.id,
                "existing_data_source_id": cross_dup.data_source_id,
                "checksum": content_checksum,
                "idempotency_key": adapter.idempotency_key,
            },
        )

    key = raw_key(
        settings,
        data_source.source_type,
        data_source.id,
        adapter.idempotency_key,
        content_checksum,
        prepared.filename,
    )
    stored = storage.put_bytes(
        key,
        prepared.content,
        prepared.mime_type,
        {
            "nexus-data-source-id": data_source.id,
            "nexus-idempotency-key": adapter.idempotency_key,
        },
    )
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=data_source.source_type,
        source_uri=prepared.source_uri,
        object_uri=stored.object_uri,
        checksum=stored.checksum,
        mime_type=prepared.mime_type,
        size_bytes=stored.size_bytes,
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary=prepared.raw_metadata,
    )
    session.add(raw)
    session.flush()
    batch.status = IngestBatchStatus.RAW_PERSISTED

    job = _create_queued_job(session, batch, raw, adapter.idempotency_key, trace_id)

    write_audit(
        session,
        AuditEventType.INGEST_BATCH_SUBMITTED,
        "ingest_batch",
        batch.id,
        trace_id,
        {"idempotency_key": adapter.idempotency_key, "object_count": 1},
    )
    write_audit(
        session,
        AuditEventType.RAW_OBJECT_PERSISTED,
        "raw_object",
        raw.id,
        trace_id,
        {"batch_id": batch.id, "checksum": raw.checksum, "size_bytes": raw.size_bytes},
    )
    notify_job_ready(session)
    session.commit()
    return IngestAccepted(batch, raw, job)


def submit_file_ingest(
    session: Session,
    payload: IngestFileSubmit,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
    trace_id: str | None = None,
) -> IngestAccepted:
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)
    return _submit_ingest(session, FileUploadAdapter(payload), storage, settings, trace_id)


def submit_crawler_package(
    session: Session,
    payload: CrawlerPackageSubmit,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
    trace_id: str | None = None,
) -> IngestAccepted:
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)
    return _submit_ingest(session, CrawlerPackageAdapter(payload), storage, settings, trace_id)
