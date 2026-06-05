"""`Job.payload_schema_version` stamping and worker-side guard.

Service-layer tests for M2 — the API contract gap is covered indirectly:
gateway stamps every new job, worker refuses anything outside the supported
set. Real pipeline behavior is exercised elsewhere; here we isolate the two
new responsibilities.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import (
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    JobStatus,
    JobType,
    RawObjectStatus,
)
from nexus_app.ingest.gateway import _create_queued_job
from nexus_app.pipeline.payload_schema import (
    JOB_PAYLOAD_SCHEMA_VERSION,
    SUPPORTED_JOB_PAYLOAD_VERSIONS,
)
from nexus_app.worker.runner import execute_job


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def seeded(session: Session) -> tuple[models.IngestBatch, models.RawObject]:
    ds = models.DataSource(
        id="ds-m2-1",
        code="ds-m2-1",
        name="M2 DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()
    batch = models.IngestBatch(
        id="batch-m2-1",
        data_source_id=ds.id,
        idempotency_key="batch-m2-1",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()
    raw = models.RawObject(
        id="raw-m2-1",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri="file://m2",
        object_uri="raw/m2",
        checksum="m2-checksum",
        size_bytes=1,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.commit()
    return batch, raw


# ── Stamping ──────────────────────────────────────────────────────────────


def test_gateway_stamps_current_schema_version(session, seeded):
    batch, raw = seeded
    job = _create_queued_job(
        session,
        batch=batch,
        raw_object=raw,
        idempotency_key="idem-m2-stamp",
        trace_id="t-1",
        pipeline_type="document",
        source_object_key=None,
    )
    session.commit()
    session.refresh(job)
    assert job.payload_schema_version == JOB_PAYLOAD_SCHEMA_VERSION
    assert JOB_PAYLOAD_SCHEMA_VERSION in SUPPORTED_JOB_PAYLOAD_VERSIONS


def test_model_default_is_v1(session, seeded):
    """A job constructed without an explicit `payload_schema_version` falls back
    to the model default — useful for migrated rows pre-0019."""
    batch, raw = seeded
    job = models.Job(
        id="job-default",
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.QUEUED,
        ingest_batch_id=batch.id,
        raw_object_id=raw.id,
        payload={"raw_object_id": raw.id, "batch_id": batch.id},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    assert job.payload_schema_version == "v1"


# ── Worker guard ──────────────────────────────────────────────────────────


def test_worker_dead_letters_unsupported_version(session, seeded, monkeypatch):
    """A worker that picks up a job stamped with an unknown version must NOT
    execute it — instead it transitions straight to dead_lettered and writes
    a PIPELINE_FAILED audit row carrying the unsupported version."""
    batch, raw = seeded
    job = models.Job(
        id="job-unsupported",
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.RUNNING,
        ingest_batch_id=batch.id,
        raw_object_id=raw.id,
        payload={"raw_object_id": raw.id, "batch_id": batch.id, "pipeline_type": "document"},
        payload_schema_version="vNEXT-impossible",
        locked_by="worker-test",
        attempt_count=1,
    )
    session.add(job)
    session.commit()

    # Stub the heavy adapters so we don't accidentally do real work if the
    # guard somehow lets execution slip through.
    from nexus_app import storage as storage_mod
    from nexus_app import mineru as mineru_mod
    from nexus_app import image_analysis as image_mod

    class _StubStorage:
        pass

    monkeypatch.setattr(storage_mod, "get_object_storage", lambda settings: _StubStorage())
    monkeypatch.setattr(mineru_mod, "get_mineru_adapter", lambda settings: object())
    monkeypatch.setattr(image_mod, "get_image_analyzer", lambda settings: object())

    execute_job(job, session)
    session.refresh(job)

    assert job.status == JobStatus.DEAD_LETTERED
    assert job.last_error_code == "unsupported_payload_schema_version"
    assert "vNEXT-impossible" in (job.failure_reason or "")
    assert job.locked_by is None

    # Audit row carries the diagnostic payload.
    audit_rows = (
        session.query(models.AuditLog)
        .filter(models.AuditLog.event_type == AuditEventType.PIPELINE_FAILED)
        .filter(models.AuditLog.target_id == job.id)
        .all()
    )
    assert len(audit_rows) == 1
    summary = audit_rows[0].summary or {}
    assert summary["error_code"] == "unsupported_payload_schema_version"
    assert summary["payload_schema_version"] == "vNEXT-impossible"
    assert summary["supported"] == sorted(SUPPORTED_JOB_PAYLOAD_VERSIONS)
