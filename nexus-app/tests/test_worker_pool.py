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
