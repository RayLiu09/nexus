from __future__ import annotations

import base64
import json
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
from nexus_app.ingest.keys import raw_key
from nexus_app.schemas import CrawlerPackageSubmit, IngestFileSubmit
from nexus_app.storage import ObjectStorage, checksum_value, get_object_storage, sha256_hex
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
    submitted_by_user_id: str | None,
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
        submitted_by_user_id=submitted_by_user_id,
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


def submit_file_ingest(
    session: Session,
    payload: IngestFileSubmit,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
    trace_id: str | None = None,
) -> IngestAccepted:
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)

    data_source = session.get(models.DataSource, payload.data_source_id)
    if data_source is None:
        raise IngestError("data_source not found")

    content = base64.b64decode(payload.content_base64)
    content_checksum = checksum_value(content)

    batch, created = _find_or_create_batch(
        session,
        payload.data_source_id,
        payload.idempotency_key,
        data_source.source_type,
        payload.submitted_by_user_id,
        {"filename": payload.filename, "object_count": 1},
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

    duplicate_raw = session.scalar(
        select(models.RawObject).where(
            models.RawObject.data_source_id == data_source.id,
            models.RawObject.checksum == content_checksum,
        )
    )
    if duplicate_raw is not None:
        batch.status = IngestBatchStatus.DUPLICATE_SKIPPED
        batch.summary = {
            **batch.summary,
            "duplicate_raw_object_id": duplicate_raw.id,
            "filename": payload.filename,
        }
        job = _create_queued_job(session, batch, duplicate_raw, payload.idempotency_key, trace_id)
        job.status = JobStatus.SUCCEEDED
        job.current_stage = "duplicate_skipped"
        write_audit(
            session,
            AuditEventType.INGEST_BATCH_SUBMITTED,
            "ingest_batch",
            batch.id,
            trace_id,
            {
                "idempotency_key": payload.idempotency_key,
                "duplicate_raw_object_id": duplicate_raw.id,
            },
        )
        session.commit()
        return IngestAccepted(batch, duplicate_raw, job)

    key = raw_key(
        settings,
        data_source.source_type,
        data_source.id,
        payload.idempotency_key,
        content_checksum,
        payload.filename,
    )
    stored = storage.put_bytes(
        key,
        content,
        payload.content_type,
        {"nexus-data-source-id": data_source.id, "nexus-idempotency-key": payload.idempotency_key},
    )
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=data_source.source_type,
        source_uri=payload.source_uri,
        object_uri=stored.object_uri,
        checksum=stored.checksum,
        mime_type=payload.content_type,
        size_bytes=stored.size_bytes,
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={"filename": payload.filename},
    )
    session.add(raw)
    session.flush()
    batch.status = IngestBatchStatus.RAW_PERSISTED

    job = _create_queued_job(session, batch, raw, payload.idempotency_key, trace_id)

    write_audit(
        session,
        AuditEventType.INGEST_BATCH_SUBMITTED,
        "ingest_batch",
        batch.id,
        trace_id,
        {"idempotency_key": payload.idempotency_key, "object_count": 1},
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


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def submit_crawler_package(
    session: Session,
    payload: CrawlerPackageSubmit,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
    trace_id: str | None = None,
) -> IngestAccepted:
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)

    data_source = session.get(models.DataSource, payload.data_source_id)
    if data_source is None:
        raise IngestError("data_source not found")

    content = _json_bytes(payload.package)
    content_checksum = checksum_value(content)

    batch, created = _find_or_create_batch(
        session,
        payload.data_source_id,
        payload.idempotency_key,
        data_source.source_type,
        payload.submitted_by_user_id,
        {"object_count": 1, "package_type": "crawler_json"},
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

    duplicate_raw = session.scalar(
        select(models.RawObject).where(
            models.RawObject.data_source_id == data_source.id,
            models.RawObject.checksum == content_checksum,
        )
    )
    if duplicate_raw is not None:
        batch.status = IngestBatchStatus.DUPLICATE_SKIPPED
        batch.summary = {**batch.summary, "duplicate_raw_object_id": duplicate_raw.id}
        job = _create_queued_job(session, batch, duplicate_raw, payload.idempotency_key, trace_id)
        job.status = JobStatus.SUCCEEDED
        job.current_stage = "duplicate_skipped"
        write_audit(
            session,
            AuditEventType.INGEST_BATCH_SUBMITTED,
            "ingest_batch",
            batch.id,
            trace_id,
            {
                "idempotency_key": payload.idempotency_key,
                "duplicate_raw_object_id": duplicate_raw.id,
            },
        )
        session.commit()
        return IngestAccepted(batch, duplicate_raw, job)

    package_id = str(
        payload.package.get("id")
        or payload.package.get("source_id")
        or sha256_hex(content)[:16]
    )
    key = raw_key(
        settings,
        data_source.source_type,
        data_source.id,
        payload.idempotency_key,
        content_checksum,
        f"{package_id}.json",
    )
    stored = storage.put_bytes(
        key,
        content,
        "application/json",
        {"nexus-data-source-id": data_source.id, "nexus-idempotency-key": payload.idempotency_key},
    )
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=data_source.source_type,
        source_uri=payload.source_uri,
        object_uri=stored.object_uri,
        checksum=stored.checksum,
        mime_type="application/json",
        size_bytes=stored.size_bytes,
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={"package_id": package_id},
    )
    session.add(raw)
    session.flush()
    batch.status = IngestBatchStatus.RAW_PERSISTED

    job = _create_queued_job(session, batch, raw, payload.idempotency_key, trace_id)

    write_audit(
        session,
        AuditEventType.INGEST_BATCH_SUBMITTED,
        "ingest_batch",
        batch.id,
        trace_id,
        {"idempotency_key": payload.idempotency_key, "object_count": 1},
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
