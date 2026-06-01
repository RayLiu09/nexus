"""Week 5 — multi-raw batch lifecycle tests.

Covers TP-W5-03 case list plus the two-step API.
"""

from __future__ import annotations

import pytest

from nexus_app import models, services
from nexus_app.config import get_settings
from nexus_app.enums import IngestBatchStatus, JobStatus
from nexus_app.ingest import batch as ingest_batch
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import DataSourceCreate
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.runner import execute_job


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _make_source(session, code: str = "fu-1", source_type: str = "file_upload"):
    return services.create_data_source(
        session,
        DataSourceCreate(code=code, name=code, source_type=source_type),
    )


def _append(session, batch_id: str, key: str, content: bytes, *, storage):
    return ingest_batch.append_file_to_batch(
        session,
        batch_id,
        file_idempotency_key=key,
        filename=f"{key}.pdf",
        content=content,
        mime_type="application/pdf",
        storage=storage,
    )


def _run_jobs(session, storage, *, mineru=None):
    mineru = mineru or FakeMinerUAdapter()
    settings = get_settings()
    jobs = claim_jobs(session, "test-worker", batch_size=20, lease_seconds=30)
    for job in jobs:
        try:
            execute_job(job, session, storage, mineru, settings)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# create_batch                                                                #
# --------------------------------------------------------------------------- #

def test_create_batch_returns_open_status_and_is_idempotent(session):
    source = _make_source(session)
    first = ingest_batch.create_batch(
        session,
        data_source_id=source.id,
        batch_idempotency_key="batch-A",
    )
    assert first.status == IngestBatchStatus.OPEN
    second = ingest_batch.create_batch(
        session,
        data_source_id=source.id,
        batch_idempotency_key="batch-A",
    )
    assert second.id == first.id


def test_create_batch_unknown_source_raises(session):
    with pytest.raises(ingest_batch.DataSourceNotFoundError):
        ingest_batch.create_batch(
            session,
            data_source_id="missing",
            batch_idempotency_key="x",
        )


# --------------------------------------------------------------------------- #
# Multi-raw success                                                            #
# --------------------------------------------------------------------------- #

def test_multi_raw_batch_all_succeed(session):
    source = _make_source(session)
    storage = InMemoryObjectStorage()
    batch = ingest_batch.create_batch(
        session,
        data_source_id=source.id,
        batch_idempotency_key="bulk-A",
    )
    for i in range(3):
        _append(session, batch.id, f"f-{i}", f"content-{i}".encode(), storage=storage)

    _run_jobs(session, storage)

    session.refresh(batch)
    assert batch.status == IngestBatchStatus.COMPLETED
    assert all(v == JobStatus.SUCCEEDED.value for v in batch.batch_status_detail.values())
    raws = services.list_rows(session, models.RawObject)
    assert len(raws) == 3


# --------------------------------------------------------------------------- #
# Partial failure                                                              #
# --------------------------------------------------------------------------- #

class _FlakyMinerU(FakeMinerUAdapter):
    """Fails for one specific filename so we can synthesize partial_failed."""

    def __init__(self, fail_substring: str) -> None:
        super().__init__()
        self._fail_substring = fail_substring

    def parse(self, filename, content, content_type=None, model_version=None):
        if self._fail_substring in filename:
            raise RuntimeError("mineru injected failure")
        return super().parse(filename, content, content_type=content_type, model_version=model_version)


def test_multi_raw_batch_partial_fail(session):
    source = _make_source(session)
    storage = InMemoryObjectStorage()
    batch = ingest_batch.create_batch(
        session,
        data_source_id=source.id,
        batch_idempotency_key="bulk-PF",
    )
    _append(session, batch.id, "good-1", b"good-1", storage=storage)
    _append(session, batch.id, "boom-1", b"boom-1", storage=storage)
    _append(session, batch.id, "good-2", b"good-2", storage=storage)

    _run_jobs(session, storage, mineru=_FlakyMinerU(fail_substring="boom"))

    session.refresh(batch)
    assert batch.status == IngestBatchStatus.PARTIAL_FAILED
    detail = batch.batch_status_detail
    succeeded = [k for k, v in detail.items() if v == JobStatus.SUCCEEDED.value]
    failed = [k for k, v in detail.items() if v == JobStatus.FAILED.value]
    assert len(succeeded) == 2 and len(failed) == 1


# --------------------------------------------------------------------------- #
# Idempotency (TP-W5-03)                                                       #
# --------------------------------------------------------------------------- #

def test_multi_raw_file_idempotency(session):
    source = _make_source(session)
    storage = InMemoryObjectStorage()
    batch = ingest_batch.create_batch(
        session,
        data_source_id=source.id,
        batch_idempotency_key="bulk-IDEM",
    )
    first = _append(session, batch.id, "dup-key", b"unique-A", storage=storage)
    second = _append(session, batch.id, "dup-key", b"different-bytes-ignored", storage=storage)

    assert second.raw_object.id == first.raw_object.id
    assert second.job.id == first.job.id
    assert second.duplicate is True
    raws = session.scalars(
        models.RawObject.__table__.select().where(models.RawObject.batch_id == batch.id)
    ).all()
    assert len(raws) == 1


# --------------------------------------------------------------------------- #
# Same-content dedup within a batch                                            #
# --------------------------------------------------------------------------- #

def test_multi_raw_same_content_dedup(session):
    source = _make_source(session)
    storage = InMemoryObjectStorage()
    batch = ingest_batch.create_batch(
        session,
        data_source_id=source.id,
        batch_idempotency_key="bulk-DEDUP",
    )
    first = _append(session, batch.id, "k1", b"same-bytes", storage=storage)
    second = _append(session, batch.id, "k2", b"same-bytes", storage=storage)

    assert second.raw_object.id == first.raw_object.id
    assert second.duplicate is True
    assert second.job.id != first.job.id
    assert second.job.current_stage == "duplicate_skipped"
    assert second.job.status == JobStatus.SUCCEEDED
    raws = services.list_rows(session, models.RawObject)
    assert len(raws) == 1


# --------------------------------------------------------------------------- #
# Cross-source duplicate writes audit                                          #
# --------------------------------------------------------------------------- #

def test_multi_raw_cross_source_audit(session):
    src_a = _make_source(session, code="A")
    src_b = _make_source(session, code="B")
    storage = InMemoryObjectStorage()
    batch_a = ingest_batch.create_batch(
        session, data_source_id=src_a.id, batch_idempotency_key="cross-A"
    )
    _append(session, batch_a.id, "k", b"shared-content", storage=storage)

    batch_b = ingest_batch.create_batch(
        session, data_source_id=src_b.id, batch_idempotency_key="cross-B"
    )
    result = _append(session, batch_b.id, "k", b"shared-content", storage=storage)

    # cross-source duplicates do not block — a fresh raw_object is created on src_b
    assert result.raw_object.data_source_id == src_b.id
    audits = services.list_rows(session, models.AuditLog)
    assert any(a.event_type.value == "CrossSourceDuplicateDetected" for a in audits)


# --------------------------------------------------------------------------- #
# Append rejection after processing                                            #
# --------------------------------------------------------------------------- #

def test_batch_append_rejected_after_processing(session):
    source = _make_source(session)
    storage = InMemoryObjectStorage()
    batch = ingest_batch.create_batch(
        session, data_source_id=source.id, batch_idempotency_key="closed"
    )
    _append(session, batch.id, "f1", b"hello", storage=storage)

    # simulate the worker picking up the queued job → batch transitions to PROCESSING
    _run_jobs(session, storage)

    session.refresh(batch)
    # all jobs succeeded so batch is now COMPLETED — anyway not OPEN/SUBMITTED/RAW_PERSISTED
    assert batch.status not in {
        IngestBatchStatus.OPEN,
        IngestBatchStatus.SUBMITTED,
        IngestBatchStatus.RAW_PERSISTED,
    }
    with pytest.raises(ingest_batch.BatchClosedError):
        _append(session, batch.id, "f2", b"world", storage=storage)


# --------------------------------------------------------------------------- #
# Aggregation pure function                                                    #
# --------------------------------------------------------------------------- #

def test_aggregate_job_statuses_rules():
    agg = ingest_batch._aggregate_job_statuses
    assert agg([]) == IngestBatchStatus.OPEN
    assert agg([JobStatus.QUEUED]) == IngestBatchStatus.PROCESSING
    assert agg([JobStatus.RUNNING, JobStatus.SUCCEEDED]) == IngestBatchStatus.PROCESSING
    assert agg([JobStatus.SUCCEEDED, JobStatus.SUCCEEDED]) == IngestBatchStatus.COMPLETED
    assert agg([JobStatus.FAILED, JobStatus.FAILED]) == IngestBatchStatus.FAILED
    assert agg([JobStatus.SUCCEEDED, JobStatus.FAILED]) == IngestBatchStatus.PARTIAL_FAILED
    assert agg([JobStatus.SUCCEEDED, JobStatus.DEAD_LETTERED]) == IngestBatchStatus.PARTIAL_FAILED
