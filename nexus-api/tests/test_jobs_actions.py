"""POST /v1/jobs/{id}/retry and /cancel."""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    JobStatus,
    JobType,
    RawObjectStatus,
)

_counter = itertools.count(1)


def _seed_job(session, status: JobStatus, attempt_count: int = 1) -> models.Job:
    nonce = next(_counter)
    source = models.DataSource(
        code=f"ds-jobs-test-{nonce}",
        name=f"DS {nonce}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(source)
    session.flush()
    batch = models.IngestBatch(
        data_source_id=source.id,
        idempotency_key=f"key-{nonce}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.SUBMITTED,
    )
    session.add(batch)
    session.flush()
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"raw://x/{nonce}",
        checksum=f"c-{nonce}",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()
    job = models.Job(
        job_type=JobType.INGEST_PROCESS,
        status=status,
        ingest_batch_id=batch.id,
        raw_object_id=raw.id,
        attempt_count=attempt_count,
        max_attempts=3,
        locked_by="worker-1" if status == JobStatus.RUNNING else None,
        next_run_at=datetime.now(timezone.utc),
        failure_reason="boom" if status == JobStatus.FAILED else None,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_retry_resets_failed_job_to_queued(app, session):
    job = _seed_job(session, JobStatus.FAILED, attempt_count=2)
    client = TestClient(app)
    resp = client.post(f"/internal/v1/jobs/{job.id}/retry")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == JobStatus.QUEUED.value
    assert body["attempt_count"] == 0

    session.refresh(job)
    assert job.status == JobStatus.QUEUED
    assert job.attempt_count == 0
    assert job.locked_by is None
    assert job.failure_reason is None

    audits = list(
        session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.JOB_RETRIED
            )
        )
    )
    assert len(audits) == 1
    assert audits[0].target_id == job.id


def test_retry_allows_dead_lettered_and_cancelled(app, session):
    for status in (JobStatus.DEAD_LETTERED, JobStatus.CANCELLED):
        job = _seed_job(session, status)
        client = TestClient(app)
        resp = client.post(f"/internal/v1/jobs/{job.id}/retry")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == JobStatus.QUEUED.value


def test_retry_rejects_succeeded_or_running(app, session):
    client = TestClient(app)
    for status in (JobStatus.SUCCEEDED, JobStatus.RUNNING, JobStatus.QUEUED):
        job = _seed_job(session, status)
        resp = client.post(f"/internal/v1/jobs/{job.id}/retry")
        assert resp.status_code == 409, f"{status} should not be retriable"


def test_cancel_queued_flips_to_cancelled_immediately(app, session):
    job = _seed_job(session, JobStatus.QUEUED)
    client = TestClient(app)
    resp = client.post(f"/internal/v1/jobs/{job.id}/cancel")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == JobStatus.CANCELLED.value
    assert body["cancel_requested_at"] is not None

    session.refresh(job)
    assert job.status == JobStatus.CANCELLED


def test_cancel_running_sets_request_and_returns_202(app, session):
    job = _seed_job(session, JobStatus.RUNNING)
    client = TestClient(app)
    resp = client.post(f"/internal/v1/jobs/{job.id}/cancel")
    assert resp.status_code == 202, resp.text
    body = resp.json()["data"]
    # Status stays running — worker hasn't observed the flag yet.
    assert body["status"] == JobStatus.RUNNING.value
    assert body["cancel_requested_at"] is not None

    session.refresh(job)
    assert job.cancel_requested_at is not None


def test_cancel_succeeded_or_already_cancelled_is_409(app, session):
    client = TestClient(app)
    succ = _seed_job(session, JobStatus.SUCCEEDED)
    assert client.post(f"/internal/v1/jobs/{succ.id}/cancel").status_code == 409

    canc = _seed_job(session, JobStatus.CANCELLED)
    assert client.post(f"/internal/v1/jobs/{canc.id}/cancel").status_code == 409


def test_cancel_returns_404_for_unknown_job(app):
    client = TestClient(app)
    assert client.post("/internal/v1/jobs/missing/cancel").status_code == 404
