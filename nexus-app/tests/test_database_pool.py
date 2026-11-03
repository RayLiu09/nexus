from types import SimpleNamespace

from nexus_app import database


def test_postgres_engine_uses_configured_pool_limits(monkeypatch):
    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(
        database_url="postgresql+psycopg://unused",
        postgres_pool_size=7, postgres_max_overflow=11,
    ))
    # Engine creation does not connect; the host is intentionally invalid.
    database.get_engine.cache_clear()
    engine = database.get_engine()
    try:
        assert engine.pool.size() == 7
        assert engine.pool._max_overflow == 11
    finally:
        engine.dispose()
        database.get_engine.cache_clear()


def test_sqlite_engine_does_not_receive_postgres_pool_options(monkeypatch):
    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(
        database_url="sqlite+pysqlite:///:memory:",
        postgres_pool_size=7, postgres_max_overflow=11,
    ))
    database.get_engine.cache_clear()
    engine = database.get_engine()
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        engine.dispose()
        database.get_engine.cache_clear()
