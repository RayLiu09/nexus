"""Scheduling and execution runtime for provider-independent sync runs."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.data_sync.catalog import _load_adapter, load_catalog
from nexus_app.data_sync.plans import next_run_time
from nexus_app.data_sync.runs import RunConflict, create_scheduled_run
from nexus_app.data_sync.tokens import TokenError, TokenManager, TokenTimeout, TokenUnavailable
from nexus_app.enums import AuditEventType, DataSyncRunStatus

logger = logging.getLogger(__name__)


class SyncRuntimeError(Exception):
    """Provider runtime error with an explicit retry classification."""

    def __init__(self, message: str, *, retryable: bool = False, code: str = "runtime_error"):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class DataSyncProvider(Protocol):
    def get_access_token(self, context: Any, client: httpx.Client): ...

    def submit(self, context: Any, query: dict[str, Any], access_token: str, idempotency_key: str): ...

    def get_status(self, context: Any, external_task_id: str, access_token: str): ...

    def fetch_page(
        self, context: Any, external_task_id: str, cursor: str | None, access_token: str
    ): ...


@dataclass(frozen=True)
class SubmitResult:
    external_task_id: str
    request_id: str | None = None


@dataclass(frozen=True)
class StatusResult:
    state: str
    request_id: str | None = None
    desired_state: str | None = None
    processed_count: int | None = None


@dataclass(frozen=True)
class PageResult:
    records: list[dict[str, Any]]
    next_cursor: str | None
    request_id: str | None = None


RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _set_status(session: Session, run: models.DataSyncRun, status: str, *, reason: str | None = None) -> None:
    previous = run.status
    if previous == status:
        return
    run.status = status
    summary = {"from": previous, "to": status}
    if reason:
        summary["reason"] = reason
    write_audit(
        session, AuditEventType.DATA_SYNC_RUN_STATUS_CHANGED, "data_sync_run", run.id,
        run.trace_id, summary, actor_type="system",
    )


def _provider_code(provider_code: str):
    item = next((entry for entry in load_catalog() if entry.provider_code == provider_code), None)
    if item is None or item.status != "enabled":
        raise SyncRuntimeError("Provider is unavailable", code="provider_unavailable")
    adapter = _load_adapter(item.adapter_factory)
    return item, adapter


def _classify_http(response: Any) -> None:
    status = getattr(response, "status_code", None)
    if status in RETRYABLE_HTTP:
        raise SyncRuntimeError(f"provider HTTP {status}", retryable=True, code=f"http_{status}")
    if status == 422:
        raise SyncRuntimeError("provider rejected request", code="http_422")
    if status == 409:
        raise SyncRuntimeError("provider request conflict", retryable=True, code="http_409")
    if isinstance(status, int) and status >= 400:
        raise SyncRuntimeError(f"provider HTTP {status}", code=f"http_{status}")


def _invoke_with_token(tokens: TokenManager, provider: Any, adapter: DataSyncProvider, operation):
    token = tokens.get_token(provider, adapter)
    for attempt in range(2):
        try:
            result = operation(token)
            _classify_http(result)
            return result
        except (SyncRuntimeError, httpx.HTTPStatusError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else (
                401 if exc.code == "http_401" else None
            )
            if status == 401 and attempt == 0:
                tokens.invalidate(provider, used_token=token)
                token = tokens.get_token(provider, adapter)
                continue
            if isinstance(exc, httpx.HTTPStatusError):
                _classify_http(exc.response)
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise SyncRuntimeError("provider request unavailable", retryable=True, code="network_error") from exc
    raise SyncRuntimeError("provider authentication failed", code="http_401")


def _coerce_submit(value: Any) -> SubmitResult:
    if isinstance(value, SubmitResult):
        return value
    if isinstance(value, dict) and isinstance(value.get("external_task_id"), str):
        return SubmitResult(value["external_task_id"], value.get("request_id"))
    raise SyncRuntimeError("provider returned invalid submit response", code="invalid_submit")


def _coerce_status(value: Any) -> StatusResult:
    if isinstance(value, StatusResult):
        return value
    if isinstance(value, dict) and isinstance(value.get("state"), str):
        return StatusResult(
            value["state"], value.get("request_id"),
            value.get("desired_state"), value.get("processed_count"),
        )
    raise SyncRuntimeError("provider returned invalid status response", code="invalid_status")


def _coerce_page(value: Any) -> PageResult:
    if isinstance(value, PageResult):
        return value
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        if not all(isinstance(row, dict) for row in value["records"]):
            raise SyncRuntimeError("provider returned invalid page records", code="invalid_page")
        return PageResult(value["records"], value.get("next_cursor"), value.get("request_id"))
    raise SyncRuntimeError("provider returned invalid page response", code="invalid_page")


class DataSyncScheduler:
    def __init__(self, session_factory: sessionmaker[Session], *, poll_interval: float = 30.0, batch_limit: int = 20):
        self._session_factory = session_factory
        self.poll_interval = max(0.1, poll_interval)
        self.batch_limit = max(1, batch_limit)

    def tick(self, now: datetime | None = None) -> int:
        now = now or _utcnow()
        providers = load_catalog()
        with self._session_factory() as session:
            plan_ids = list(session.scalars(
                select(models.DataSyncConfig.id)
                .where(
                    models.DataSyncConfig.status == "active",
                    models.DataSyncConfig.next_run_at.is_not(None),
                    models.DataSyncConfig.next_run_at <= now,
                )
                .order_by(models.DataSyncConfig.next_run_at.asc())
                .limit(self.batch_limit)
            ))
        fired = 0
        for plan_id in plan_ids:
            with self._session_factory() as session:
                plan = session.scalar(select(models.DataSyncConfig).where(
                    models.DataSyncConfig.id == plan_id,
                    models.DataSyncConfig.status == "active",
                    models.DataSyncConfig.next_run_at <= now,
                ).with_for_update(skip_locked=True))
                if plan is None:
                    continue
                slot = plan.next_run_at
                if slot is None:
                    continue
                if slot.tzinfo is None or slot.utcoffset() is None:
                    slot = slot.replace(tzinfo=timezone.utc)
                existing = session.scalar(select(models.DataSyncRun.id).where(
                    models.DataSyncRun.data_sync_config_id == plan.id,
                    models.DataSyncRun.scheduled_slot == slot,
                ))
                try:
                    create_scheduled_run(
                        session, plan_id=plan.id, scheduled_slot=slot,
                        trace_id=uuid.uuid4().hex, providers=providers,
                    )
                    if existing is None:
                        fired += 1
                except RunConflict:
                    # A previous run can still be active; the schedule advances
                    # so a later tick cannot create duplicate work for the slot.
                    pass
                plan.next_run_at = next_run_time(now, plan.frequency)
                session.commit()
        return fired

    def run_until_stopped(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("data sync scheduler tick failed")
            stop_event.wait(self.poll_interval)


def claim_run(session: Session, worker_id: str, *, lease_seconds: int = 120) -> models.DataSyncRun | None:
    now = _utcnow()
    run = session.scalar(
        select(models.DataSyncRun)
        .where(
            (models.DataSyncRun.status == DataSyncRunStatus.QUEUED.value)
            | ((models.DataSyncRun.status == DataSyncRunStatus.RUNNING.value)
               & models.DataSyncRun.claim_owner.is_(None)),
            (models.DataSyncRun.next_retry_at.is_(None) | (models.DataSyncRun.next_retry_at <= now)),
        )
        .order_by(models.DataSyncRun.queued_at.asc(), models.DataSyncRun.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        return None
    if run.status == DataSyncRunStatus.QUEUED.value:
        _set_status(session, run, DataSyncRunStatus.RUNNING.value)
    run.claim_owner = worker_id
    run.heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    run.started_at = run.started_at or now
    run.attempt_count += 1
    session.commit()
    session.refresh(run)
    return run


def heartbeat(session_factory: sessionmaker[Session], run_id: str, worker_id: str, lease_seconds: int) -> bool:
    with session_factory() as session:
        run = session.scalar(select(models.DataSyncRun).where(
            models.DataSyncRun.id == run_id,
        ).with_for_update())
        if run is None or run.status != DataSyncRunStatus.RUNNING.value or run.claim_owner != worker_id:
            return False
        now = _utcnow()
        run.heartbeat_at = now
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        session.commit()
        return True


def recover_expired_runs(session: Session, *, now: datetime | None = None, max_attempts: int = 3) -> int:
    now = now or _utcnow()
    rows = list(session.scalars(select(models.DataSyncRun).where(
        models.DataSyncRun.status == DataSyncRunStatus.RUNNING.value,
        models.DataSyncRun.lease_expires_at < now,
    ).with_for_update(skip_locked=True)))
    for run in rows:
        run.claim_owner = None
        run.lease_expires_at = None
        run.heartbeat_at = None
        if run.attempt_count >= max_attempts:
            _set_status(session, run, DataSyncRunStatus.FAILED.value, reason="lease_expired")
            run.finished_at = now
            run.failure_summary = "worker lease expired after maximum attempts"
        else:
            _set_status(session, run, DataSyncRunStatus.QUEUED.value, reason="lease_expired")
            run.next_retry_at = now
            run.failure_summary = "worker lease expired; requeued"
    if rows:
        session.commit()
    return len(rows)


class DataSyncExecutor:
    def __init__(self, session_factory: sessionmaker[Session], *, worker_id: str, lease_seconds: int = 120, max_attempts: int = 3):
        self._session_factory = session_factory
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self._client = httpx.Client(timeout=30.0)
        self._tokens = TokenManager(self._client)

    def close(self) -> None:
        self._client.close()

    def run_once(self) -> bool:
        with self._session_factory() as session:
            run = claim_run(session, self.worker_id, lease_seconds=self.lease_seconds)
        if run is None:
            return False
        stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(run.id, stop),
            name=f"data-sync-heartbeat-{run.id[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            self._execute(run.id)
        except Exception as exc:
            self._fail_or_retry(run.id, exc)
        finally:
            stop.set()
            heartbeat_thread.join(timeout=1.0)
        return True

    def _heartbeat_loop(self, run_id: str, stop: threading.Event) -> None:
        interval = max(0.1, min(30.0, self.lease_seconds / 3))
        while not stop.wait(interval):
            try:
                alive = heartbeat(self._session_factory, run_id, self.worker_id, self.lease_seconds)
            except Exception:
                logger.error("data sync heartbeat failed run_id=%s", run_id)
                return
            if not alive:
                return

    def _execute(self, run_id: str) -> None:
        with self._session_factory() as session:
            run = session.get(models.DataSyncRun, run_id)
            if run is None or run.status != DataSyncRunStatus.RUNNING.value or run.claim_owner != self.worker_id:
                return
            plan = session.get(models.DataSyncConfig, run.data_sync_config_id)
            if plan is None:
                raise SyncRuntimeError("sync plan not found", code="plan_missing")
            provider_code = plan.provider_code
            external_task_id = run.external_task_id
            query_snapshot = dict(run.query_snapshot)
        provider, adapter = _provider_code(provider_code)
        if not external_task_id:
            try:
                submitted = _invoke_with_token(
                    self._tokens, provider, adapter,
                    lambda token: adapter.submit(provider, query_snapshot, token, run_id),
                )
            except SyncRuntimeError as exc:
                recover = getattr(adapter, "recover_task", None)
                if exc.code != "http_409" or not callable(recover):
                    raise
                submitted = _invoke_with_token(
                    self._tokens, provider, adapter,
                    lambda token: recover(provider, run_id, token),
                )
            result = _coerce_submit(submitted)
            with self._session_factory() as session:
                run = session.scalar(select(models.DataSyncRun).where(
                    models.DataSyncRun.id == run_id,
                ).with_for_update())
                if run is None or run.status != "running" or run.claim_owner != self.worker_id:
                    return
                run.external_task_id = result.external_task_id
                run.request_id = result.request_id
                session.commit()
        self._poll_pages(run_id, provider, adapter)

    def _poll_pages(self, run_id: str, provider: Any, adapter: DataSyncProvider) -> None:
        handler = getattr(adapter, "result_handler", None)
        while True:
            with self._session_factory() as session:
                run = session.get(models.DataSyncRun, run_id)
                if run is None or run.status != DataSyncRunStatus.RUNNING.value or run.claim_owner != self.worker_id:
                    return
                external_task_id = run.external_task_id
                cursor = run.last_cursor
            status = _coerce_status(_invoke_with_token(
                self._tokens, provider, adapter,
                lambda token: adapter.get_status(provider, external_task_id, token),
            ))
            if status.state not in {
                "failed", "cancelled", "paused", "succeeded", "partially_succeeded",
                "completed", "ready",
            }:
                with self._session_factory() as session:
                    run = session.scalar(select(models.DataSyncRun).where(
                        models.DataSyncRun.id == run_id,
                    ).with_for_update())
                    if run is None or run.status != "running" or run.claim_owner != self.worker_id:
                        return
                    run.external_status = status.state
                    run.status_detail = {
                        "desired_state": status.desired_state,
                        "upstream_processed_count": status.processed_count,
                    }
                    run.last_polled_at = _utcnow()
                    session.commit()
                raise SyncRuntimeError("provider task is not ready", retryable=True, code="not_ready")
            page = None
            if status.state != "paused":
                page = _coerce_page(_invoke_with_token(
                    self._tokens, provider, adapter,
                    lambda token: adapter.fetch_page(provider, external_task_id, cursor, token),
                ))
            with self._session_factory() as session:
                run = session.scalar(select(models.DataSyncRun).where(
                    models.DataSyncRun.id == run_id,
                ).with_for_update())
                if run is None or run.status != "running" or run.claim_owner != self.worker_id:
                    return
                if run.last_cursor != cursor:
                    return
                run.external_status = status.state
                run.request_id = status.request_id or run.request_id
                run.status_detail = {
                    "desired_state": status.desired_state,
                    "upstream_processed_count": status.processed_count,
                }
                if status.state == "paused":
                    _set_status(session, run, "paused", reason="provider_paused")
                    run.claim_owner = None
                    run.lease_expires_at = None
                    run.heartbeat_at = None
                    session.commit()
                    return
                assert page is not None
                if handler is not None:
                    intake = handler.accept_page(session, run, page.records)
                    accepted, duplicate = intake.accepted, intake.duplicate
                else:
                    accepted, duplicate = len(page.records), 0
                run.processed_count += len(page.records)
                run.success_count += accepted
                run.skipped_count += duplicate
                run.last_cursor = page.next_cursor
                run.last_polled_at = _utcnow()
                run.request_id = page.request_id or run.request_id
                if page.next_cursor is None:
                    final_status = {
                        "failed": "failed",
                        "cancelled": "cancelled",
                        "partially_succeeded": "partially_succeeded",
                    }.get(status.state, "succeeded")
                    if final_status == "succeeded" and run.failure_count:
                        final_status = "partially_succeeded"
                    _set_status(
                        session, run, final_status,
                    )
                    run.finished_at = _utcnow()
                    run.claim_owner = None
                    run.lease_expires_at = None
                    run.heartbeat_at = None
                    run.failure_summary = (
                        "provider reported failure" if final_status == "failed" else None
                    )
                session.commit()
                if page.next_cursor is None:
                    return

    def _fail_or_retry(self, run_id: str, exc: Exception) -> None:
        with self._session_factory() as session:
            run = session.scalar(select(models.DataSyncRun).where(
                models.DataSyncRun.id == run_id,
            ).with_for_update())
            if run is None or run.status != DataSyncRunStatus.RUNNING.value or run.claim_owner != self.worker_id:
                return
            retryable = isinstance(exc, (TokenTimeout, TokenUnavailable)) or (
                isinstance(exc, SyncRuntimeError) and exc.retryable
            )
            waiting = isinstance(exc, SyncRuntimeError) and exc.code == "not_ready"
            if waiting:
                run.attempt_count = max(0, run.attempt_count - 1)
                run.next_retry_at = _utcnow() + timedelta(seconds=5)
                run.failure_summary = None
            elif retryable and run.attempt_count < self.max_attempts:
                delay = min(300, 2 ** max(0, run.attempt_count - 1) * 5)
                _set_status(session, run, DataSyncRunStatus.QUEUED.value, reason="retry")
                run.next_retry_at = _utcnow() + timedelta(seconds=delay)
            else:
                _set_status(session, run, DataSyncRunStatus.FAILED.value, reason="execution_error")
                run.finished_at = _utcnow()
            if not waiting:
                run.failure_summary = (
                    exc.code if isinstance(exc, SyncRuntimeError)
                    else exc.code if isinstance(exc, TokenError)
                    else type(exc).__name__
                )[:2000]
            run.claim_owner = None
            run.lease_expires_at = None
            run.heartbeat_at = None
            session.commit()


class DataSyncWorker:
    def __init__(
        self, session_factory: sessionmaker[Session], *, worker_id: str,
        poll_interval: float = 5.0, lease_seconds: int = 120, max_attempts: int = 3,
    ):
        self._session_factory = session_factory
        self._poll_interval = max(0.1, poll_interval)
        self._executor = DataSyncExecutor(
            session_factory, worker_id=worker_id,
            lease_seconds=lease_seconds, max_attempts=max_attempts,
        )
        self._lease_seconds = lease_seconds

    def run_until_stopped(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                try:
                    with self._session_factory() as session:
                        recover_expired_runs(session, max_attempts=self._executor.max_attempts)
                    processed = self._executor.run_once()
                except Exception:
                    logger.error("data sync worker iteration failed")
                    processed = False
                if not processed:
                    stop_event.wait(self._poll_interval)
        finally:
            self._executor.close()
