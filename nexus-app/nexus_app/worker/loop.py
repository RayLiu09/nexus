from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_app import models
from nexus_app.config import Settings, get_settings
from nexus_app.enums import JobStatus
from nexus_app.mineru import MinerUAdapter, get_mineru_adapter
from nexus_app.models import utcnow
from nexus_app.storage import ObjectStorage, get_object_storage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.notify import JobNotifier
from nexus_app.worker.runner import (
    NonRetryableError,
    RetryableError,
    _add_failure_stage,
    _mark_job_outcome,
    execute_job,
)

logger = logging.getLogger(__name__)


class _LeaseHeartbeat:
    def __init__(
        self,
        session_factory,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"nexus-lease-heartbeat-{job_id[:8]}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        interval = max(1.0, min(30.0, self._lease_seconds / 3))
        while not self._stop_event.wait(interval):
            try:
                with self._session_factory() as session:
                    job = session.get(models.Job, self._job_id)
                    if job is None:
                        return
                    if job.status != JobStatus.RUNNING or job.locked_by != self._worker_id:
                        return
                    job.lock_expires_at = utcnow() + timedelta(seconds=self._lease_seconds)
                    session.commit()
            except Exception:
                logger.exception("lease heartbeat failed for job %s", self._job_id)


def recovery_sweep(session: Session, lease_seconds: int = 120) -> int:
    """Scan running jobs with expired leases, requeue or dead-letter them."""
    now = utcnow()
    expired = list(
        session.scalars(
            select(models.Job).where(
                models.Job.status == JobStatus.RUNNING,
                models.Job.lock_expires_at < now,
            )
        ).all()
    )
    recovered = 0
    for job in expired:
        reason = f"lock_expired at {job.lock_expires_at}"
        if job.current_stage:
            _add_failure_stage(session, job, job.current_stage, reason)
        if job.attempt_count >= job.max_attempts:
            _mark_job_outcome(session, job, reason, job.trace_id, NonRetryableError(reason, "lock_expired"))
        else:
            _mark_job_outcome(session, job, reason, job.trace_id, RetryableError(reason))
        recovered += 1
    if recovered:
        session.commit()
    return recovered


class WorkerLoop:
    def __init__(
        self,
        worker_id: str | None = None,
        session_factory: sessionmaker | None = None,
        storage: ObjectStorage | None = None,
        mineru: MinerUAdapter | None = None,
        settings: Settings | None = None,
        max_concurrent: int = 8,
        poll_interval_seconds: float = 5.0,
        lease_seconds: int = 120,
    ) -> None:
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._session_factory = session_factory
        self._storage = storage
        self._mineru = mineru
        self._settings = settings or get_settings()
        self.max_concurrent = max_concurrent
        # poll_interval_seconds is the safety-net polling interval when idle
        # and no NOTIFY arrives.  With LISTEN/NOTIFY active this fires rarely.
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_seconds = lease_seconds
        self._notifier = JobNotifier(self._settings.database_url)

    def _get_session(self) -> Session:
        if self._session_factory is not None:
            return self._session_factory()
        from nexus_app.database import get_session_local
        return get_session_local()()

    def _get_storage(self) -> ObjectStorage:
        if self._storage is not None:
            return self._storage
        return get_object_storage(self._settings)

    def _get_mineru(self) -> MinerUAdapter:
        if self._mineru is not None:
            return self._mineru
        return get_mineru_adapter(self._settings)

    def run_once(self) -> int:
        """Claim and execute one batch of jobs. Returns number of jobs processed."""
        with self._get_session() as session:
            jobs = claim_jobs(
                session,
                self.worker_id,
                batch_size=min(4, self.max_concurrent),
                lease_seconds=self.lease_seconds,
            )

        if not jobs:
            return 0

        storage = self._get_storage()
        mineru = self._get_mineru()
        processed = 0

        for job in jobs:
            with self._get_session() as session:
                fresh_job = session.get(models.Job, job.id)
                if fresh_job is None:
                    continue
                heartbeat = _LeaseHeartbeat(
                    self._get_session,
                    fresh_job.id,
                    self.worker_id,
                    self.lease_seconds,
                )
                heartbeat.start()
                try:
                    execute_job(fresh_job, session, storage, mineru, self._settings)
                    processed += 1
                except Exception:
                    logger.exception("job %s failed in worker", job.id)
                    processed += 1
                finally:
                    heartbeat.stop()

        return processed

    def run_until_stopped(self, stop_event: threading.Event) -> None:
        """Run the worker loop until `stop_event` is set."""
        logger.info("worker %s starting", self.worker_id)
        sweep_interval = 60
        last_sweep = time.monotonic()

        while not stop_event.is_set():
            try:
                count = self.run_once()
                if count == 0:
                    if getattr(self._notifier, "_available", False):
                        notified = self._notifier.wait(timeout=self.poll_interval_seconds)
                        if notified:
                            logger.debug("worker %s woke via NOTIFY", self.worker_id)
                    else:
                        stop_event.wait(timeout=self.poll_interval_seconds)
            except Exception:
                logger.exception("worker loop error")
                if getattr(self._notifier, "_available", False):
                    self._notifier.wait(timeout=self.poll_interval_seconds)
                else:
                    stop_event.wait(timeout=self.poll_interval_seconds)

            now_mono = time.monotonic()
            if now_mono - last_sweep >= sweep_interval:
                try:
                    with self._get_session() as session:
                        recovered = recovery_sweep(session, self.lease_seconds)
                    if recovered:
                        logger.info("recovery_sweep recovered %d jobs", recovered)
                except Exception:
                    logger.exception("recovery sweep error")
                last_sweep = now_mono

        logger.info("worker %s stopping", self.worker_id)

    def run_forever(self) -> None:
        """Main loop: pull-based wakeup via LISTEN/NOTIFY + safety-net polling.

        When a new job is submitted the gateway fires pg_notify('nexus_jobs').
        The worker wakes immediately via the LISTEN connection and calls run_once().
        If no notification arrives within poll_interval_seconds, run_once() is
        called anyway so stale retries and recovered jobs are never stuck.
        """
        self.run_until_stopped(threading.Event())

    def close(self) -> None:
        self._notifier.close()
