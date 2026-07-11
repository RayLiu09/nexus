"""Global pytest fixtures.

Two ``session`` fixtures backends coexist:

* Default (**SQLite in-memory**) — fast, fully isolated per test.  The
  vast majority of unit + integration tests use this.
* Opt-in **Postgres + pgvector** — activated via
  ``NEXUS_GOLDEN_USE_POSTGRES=1``.  Runs against the DB defined by the
  ``Settings.database_url`` computed field (which reads ``.env.dev``).
  Used by M-C.3 to exercise the real ``vector`` extension code path in
  ``PgvectorSearchAdapter`` and the PR-7b ``ANY(:chunk_ids)`` SQL.

Postgres isolation follows the SQLAlchemy 2.x "outer transaction +
savepoint" pattern: an outer ``connection.begin()`` wraps the entire
test, and the Session is bound with ``join_transaction_mode=
"create_savepoint"`` so any ``session.commit()`` inside a seed only
releases a savepoint — the outer transaction rolls back at fixture
teardown, undoing every row (and safely leaving schema intact).

Assumes the Postgres DB has ``alembic upgrade head`` already applied —
this fixture never runs DDL against Postgres because CREATE TABLE
inside the outer transaction would rollback with the rest.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_app import database
from nexus_app.database import Base


def _postgres_mode_enabled() -> bool:
    return os.getenv("NEXUS_GOLDEN_USE_POSTGRES", "").lower() in (
        "1", "true", "yes", "on",
    )


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    database.get_engine.cache_clear()
    database.get_session_local.cache_clear()
    try:
        if _postgres_mode_enabled():
            yield from _postgres_session()
        else:
            yield from _sqlite_session()
    finally:
        database.get_engine.cache_clear()
        database.get_session_local.cache_clear()


def _sqlite_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    with TestingSession() as db:
        yield db


def _postgres_session() -> Generator[Session, None, None]:
    from nexus_app.config import get_settings

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)

    connection = engine.connect()
    # Outer transaction — every session.commit() inside the test only
    # releases a savepoint (join_transaction_mode); this rollback at
    # the end undoes all writes and keeps the shared DB clean.
    transaction = connection.begin()
    TestingSession = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
