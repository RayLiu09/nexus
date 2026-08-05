"""Regression coverage for Worker lease ownership before job execution."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from nexus_app import models
from nexus_app.config import Settings
from nexus_app.enums import IndexManifestStatus, JobStatus, JobType, StageStatus
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker import loop as worker_loop_module
from nexus_app.worker.loop import WorkerLoop
from nexus_app.worker.runner import (
    RetryableError,
    _require_continuation_indexed,
    execute_job,
)


def _session_factory(session):
    return sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


def _queued_job(session, *, job_type: JobType = JobType.KNOWLEDGE_CONTINUATION):
    job = models.Job(
        job_type=job_type,
        status=JobStatus.QUEUED,
        idempotency_key=f"worker-lease-{job_type.value}",
        current_stage="queued",
        payload={"pipeline_type": "document"},
    )
    session.add(job)
    session.commit()
    return job


class _RecordingHeartbeat:
    started = False

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def start(self) -> None:
        type(self).started = True

    def stop(self) -> None:
        pass


def test_heartbeat_starts_before_dependency_initialization(session, monkeypatch):
    job = _queued_job(session)
    _RecordingHeartbeat.started = False
    loop = WorkerLoop(
        worker_id="lease-order",
        session_factory=_session_factory(session),
        settings=Settings(worker_pool_enabled=False),
        lease_seconds=30,
    )
    monkeypatch.setattr(worker_loop_module, "_LeaseHeartbeat", _RecordingHeartbeat)

    def storage_factory():
        assert _RecordingHeartbeat.started is True
        return InMemoryObjectStorage()

    monkeypatch.setattr(loop, "_get_storage", storage_factory)
    monkeypatch.setattr(
        worker_loop_module,
        "execute_job",
        lambda *_args, **_kwargs: None,
    )

    assert loop.run_once() == 1
    assert job.id


def test_knowledge_continuation_does_not_initialize_mineru(session, monkeypatch):
    _queued_job(session)
    loop = WorkerLoop(
        worker_id="continuation-no-mineru",
        session_factory=_session_factory(session),
        settings=Settings(worker_pool_enabled=False),
        lease_seconds=30,
    )
    monkeypatch.setattr(worker_loop_module, "_LeaseHeartbeat", _RecordingHeartbeat)
    monkeypatch.setattr(loop, "_get_storage", lambda: InMemoryObjectStorage())
    monkeypatch.setattr(
        loop,
        "_get_mineru",
        lambda: (_ for _ in ()).throw(AssertionError("MinerU must not initialize")),
    )
    monkeypatch.setattr(worker_loop_module, "execute_job", lambda *_args, **_kwargs: None)

    assert loop.run_once() == 1


def test_worker_loop_claims_one_job_per_serial_executor(session, monkeypatch):
    _queued_job(session)
    seen: dict[str, int] = {}
    loop = WorkerLoop(
        worker_id="serial-claim",
        session_factory=_session_factory(session),
        settings=Settings(worker_pool_enabled=False),
        max_concurrent=8,
        lease_seconds=30,
    )
    monkeypatch.setattr(worker_loop_module, "_LeaseHeartbeat", _RecordingHeartbeat)
    monkeypatch.setattr(loop, "_get_storage", lambda: InMemoryObjectStorage())
    monkeypatch.setattr(worker_loop_module, "execute_job", lambda *_args, **_kwargs: None)
    real_claim_jobs = worker_loop_module.claim_jobs

    def recording_claim_jobs(*args, **kwargs):
        seen["batch_size"] = kwargs["batch_size"]
        return real_claim_jobs(*args, **kwargs)

    monkeypatch.setattr(worker_loop_module, "claim_jobs", recording_claim_jobs)

    assert loop.run_once() == 1
    assert seen["batch_size"] == 1


def test_dependency_initialization_failure_releases_running_job(session, monkeypatch):
    job = _queued_job(session)
    loop = WorkerLoop(
        worker_id="dependency-failure",
        session_factory=_session_factory(session),
        settings=Settings(worker_pool_enabled=False),
        lease_seconds=30,
    )
    monkeypatch.setattr(worker_loop_module, "_LeaseHeartbeat", _RecordingHeartbeat)
    monkeypatch.setattr(
        loop,
        "_get_storage",
        lambda: (_ for _ in ()).throw(RetryableError("storage temporarily unavailable")),
    )

    assert loop.run_once() == 1
    session.expire_all()
    persisted = session.get(models.Job, job.id)
    assert persisted.status == JobStatus.QUEUED
    assert persisted.locked_by is None
    assert persisted.lock_expires_at is None
    stage = session.query(models.JobStage).filter_by(
        job_id=job.id, stage_name="initializing_dependencies"
    ).one()
    assert stage.status == StageStatus.FAILED


def test_direct_continuation_execution_does_not_construct_mineru(session, monkeypatch):
    job = _queued_job(session)
    job.status = JobStatus.RUNNING
    session.commit()
    monkeypatch.setattr(
        "nexus_app.worker.runner.get_mineru_adapter",
        lambda _settings: (_ for _ in ()).throw(AssertionError("MinerU must not initialize")),
    )
    monkeypatch.setattr(
        "nexus_app.worker.runner._execute_knowledge_continuation",
        lambda *_args, **_kwargs: None,
    )

    execute_job(
        job,
        session,
        storage=InMemoryObjectStorage(),
        mineru=None,
        settings=Settings(worker_pool_enabled=False),
    )


def test_knowledge_continuation_requires_every_chunk_type_to_be_indexed():
    chunks = [
        SimpleNamespace(knowledge_type_code="course_textbook"),
        SimpleNamespace(knowledge_type_code="industry_research_kb"),
    ]
    manifests = [
        SimpleNamespace(
            knowledge_type_code="course_textbook",
            index_status=IndexManifestStatus.INDEXED,
        ),
        SimpleNamespace(
            knowledge_type_code="industry_research_kb",
            index_status=IndexManifestStatus.FAILED,
        ),
    ]

    with pytest.raises(RetryableError, match="industry_research_kb"):
        _require_continuation_indexed(chunks, manifests)


def test_knowledge_continuation_accepts_fully_indexed_chunk_types():
    chunks = [SimpleNamespace(knowledge_type_code="course_textbook")]
    manifests = [
        SimpleNamespace(
            knowledge_type_code="course_textbook",
            index_status=IndexManifestStatus.INDEXED,
        )
    ]

    _require_continuation_indexed(chunks, manifests)
