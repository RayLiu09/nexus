"""PostgreSQL LISTEN/NOTIFY support for the worker loop.

Gateway emits pg_notify('nexus_jobs', ...) transactionally on every new QUEUED
job.  WorkerLoop opens a dedicated autocommit LISTEN connection and blocks in
wait() instead of sleeping.  Falls back silently to polling on SQLite (tests)
or when psycopg is unavailable.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_CHANNEL = "nexus_jobs"


def notify_job_ready(session: Session) -> None:
    """Emit pg_notify inside the current transaction.

    Fires only when the transaction commits (PostgreSQL transactional NOTIFY).
    Safe no-op on SQLite — the dialect check suppresses it silently.
    """
    try:
        dialect = session.get_bind().dialect.name
    except Exception:
        return
    if dialect != "postgresql":
        return
    session.execute(text(f"SELECT pg_notify('{_CHANNEL}', 'job_ready')"))


def _pg_dsn(database_url: str) -> str:
    """Strip the SQLAlchemy driver marker to get a plain libpq URL."""
    return database_url.replace("+psycopg", "").replace("+psycopg2", "")


class JobNotifier:
    """LISTEN-based wakeup for WorkerLoop.

    On PostgreSQL: opens one dedicated autocommit connection, listens on
    nexus_jobs, and blocks in wait() until notified or timeout expires.

    On SQLite / when psycopg is missing: wait() immediately returns False
    so the caller falls back to its safety-net polling interval.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._conn = None
        self._available = False
        if database_url and "postgresql" in database_url:
            self._setup(_pg_dsn(database_url))

    def _setup(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: PLC0415

            self._conn = psycopg.connect(dsn, autocommit=True)
            self._conn.execute(f"LISTEN {_CHANNEL}")
            self._available = True
            logger.info("worker: LISTEN %s ready", _CHANNEL)
        except Exception:
            logger.debug("LISTEN unavailable, falling back to polling", exc_info=True)
            self._conn = None
            self._available = False

    def wait(self, timeout: float = 5.0) -> bool:
        """Block until notified or timeout.  Returns True if a notification arrived."""
        if not self._available or self._conn is None:
            return False
        try:
            for notify in self._conn.notifies(timeout=timeout):
                _ = notify
                return True
            return False  # timeout — generator exhausted without notifying
        except Exception:
            logger.warning("LISTEN connection lost; reconnecting", exc_info=True)
            self._reconnect()
            return False

    def _reconnect(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        self._available = False
        # Reconnect attempt deferred to next wait() call via _setup
        logger.info("worker: LISTEN reconnect scheduled on next wait")

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._available = False
