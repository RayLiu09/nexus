import time

from nexus_app.config import Settings
from nexus_app.worker.pool import WorkerPool


def test_worker_pool_disabled_does_not_start_threads():
    settings = Settings(
        worker_pool_enabled=False,
        worker_pool_size=2,
        postgres_driver="sqlite+pysqlite",
        postgres_db=":memory:",
        nexus_database_url="sqlite+pysqlite:///:memory:",
    )

    pool = WorkerPool(settings)
    pool.start()

    state = pool.state()
    assert state.enabled is False
    assert state.configured_size == 2
    assert state.running_threads == 0


def test_worker_pool_start_stop_with_sqlite_polling():
    settings = Settings(
        worker_pool_enabled=True,
        worker_pool_size=1,
        worker_poll_interval_seconds=0.05,
        worker_lease_seconds=30,
        worker_max_concurrent=1,
        postgres_driver="sqlite+pysqlite",
        postgres_db=":memory:",
        nexus_database_url="sqlite+pysqlite:///:memory:",
        mineru_use_fake=True,
    )

    pool = WorkerPool(settings)
    pool.start()
    time.sleep(0.02)

    assert pool.state().running_threads == 1

    pool.stop(timeout=1)
    assert pool.state().running_threads == 0


def test_claim_jobs_returns_fresh_running_jobs(session):
    import base64

    from nexus_app import services
    from nexus_app.enums import JobStatus
    from nexus_app.ingest import gateway as ingest_gateway
    from nexus_app.schemas import DataSourceCreate, IngestFileSubmit
    from nexus_app.storage import InMemoryObjectStorage
    from nexus_app.worker.claimer import claim_jobs

    source = services.create_data_source(
        session,
        DataSourceCreate(code="claim-source", name="Claim Source", source_type="file_upload"),
    )
    accepted = ingest_gateway.submit_file_ingest(
        session,
        IngestFileSubmit(
            data_source_id=source.id,
            idempotency_key="claim-file",
            filename="claim.pdf",
            content_base64=base64.b64encode(b"x").decode("ascii"),
        ),
        storage=InMemoryObjectStorage(),
    )

    claimed = claim_jobs(session, "claim-worker", batch_size=1, lease_seconds=30)

    assert len(claimed) == 1
    assert claimed[0].id == accepted.job.id
    assert claimed[0].status == JobStatus.RUNNING
    assert claimed[0].attempt_count == 1
    assert claimed[0].locked_by == "claim-worker"
