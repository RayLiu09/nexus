from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
import httpx

from nexus_app import models
from nexus_app.data_sync.plans import create_plan
from nexus_app.data_sync.runtime import (
    DataSyncExecutor,
    DataSyncScheduler,
    PageResult,
    StatusResult,
    SubmitResult,
    SyncRuntimeError,
    claim_run,
    recover_expired_runs,
)
from nexus_app.data_sync.runs import create_manual_run
from nexus_app.enums import AuditEventType


def _plan(session):
    return create_plan(
        session,
        name="Runtime plan",
        provider_code="mock",
        frequency="1_month",
        query_config={"keyword": "runtime"},
        actor_id="admin",
        idempotency_key="runtime-plan",
        trace_id="trace-plan",
    )


def test_claim_heartbeat_and_expired_run_recovery(session):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="runtime-run", trace_id="trace-run"
    )
    claimed = claim_run(session, "runtime-worker", lease_seconds=10)
    assert claimed is not None
    assert claimed.id == run.id
    assert claimed.status == "running"
    claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    assert recover_expired_runs(session, max_attempts=3) == 1
    assert session.get(models.DataSyncRun, run.id).status == "queued"


def test_expired_unconfirmed_submit_can_replay_after_attempt_limit(session):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="expired-submit",
        trace_id="trace-expired-submit",
    )
    claimed = claim_run(session, "crashed-worker", lease_seconds=10)
    assert claimed.id == run.id
    claimed.attempt_count = 3
    claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    assert recover_expired_runs(session, max_attempts=3) == 1
    assert session.get(models.DataSyncRun, run.id).status == "queued"


def test_scheduler_creates_due_run_and_advances_plan(session):
    plan = _plan(session)
    plan.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    scheduler = DataSyncScheduler(factory, poll_interval=1)
    assert scheduler.tick(datetime.now(timezone.utc)) == 1
    assert plan.next_run_at is not None
    runs = list(session.scalars(select(models.DataSyncRun).where(
        models.DataSyncRun.data_sync_config_id == plan.id,
    )))
    assert len(runs) == 1
    assert runs[0].scheduled_slot is not None
    plan.status = "paused"
    plan.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.commit()
    assert scheduler.tick(datetime.now(timezone.utc)) == 0
    assert len(list(session.scalars(select(models.DataSyncRun).where(
        models.DataSyncRun.data_sync_config_id == plan.id,
    )))) == 1


class _FakeAdapter:
    def __init__(self):
        self.pages = 0

    def submit(self, context, query, access_token, idempotency_key):
        return SubmitResult("external-1", "request-1")

    def get_status(self, context, external_task_id, access_token):
        return StatusResult("succeeded", "request-2")

    def fetch_page(self, context, external_task_id, cursor, access_token):
        self.pages += 1
        return PageResult([{"id": self.pages}], None, "request-3")


def test_executor_persists_external_ids_page_counts_and_terminal_state(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="executor-run", trace_id="trace-run"
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    adapter = _FakeAdapter()
    provider = type("Provider", (), {
        "provider_code": "mock", "api_server_url": "http://localhost",
        "tenant_id": "tenant", "tenant_key": type("Key", (), {"get_secret_value": lambda _: "key"})(),
    })()
    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (provider, adapter))
    executor = DataSyncExecutor(factory, worker_id="executor-worker")
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once() is True
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "succeeded", refreshed.failure_summary
    assert refreshed.external_task_id == "external-1"
    assert refreshed.processed_count == 1
    assert refreshed.success_count == 1
    transitions = list(session.scalars(select(models.AuditLog).where(
        models.AuditLog.target_id == run.id,
        models.AuditLog.event_type == AuditEventType.DATA_SYNC_RUN_STATUS_CHANGED,
    )))
    assert [row.summary["to"] for row in transitions] == ["running", "succeeded"]


def test_builtin_mock_provider_completes_two_page_run(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="builtin-mock",
        trace_id="trace-mock",
    )
    executor = DataSyncExecutor(
        sessionmaker(bind=session.get_bind(), expire_on_commit=False), worker_id="mock-worker"
    )
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "succeeded"
    assert refreshed.external_task_id == f"mock-{run.id}"
    assert refreshed.processed_count == 1
    assert refreshed.last_cursor is None


def test_runtime_retries_503_and_fails_422_without_storing_response(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="http-retry",
        trace_id="trace-http",
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    class FailingAdapter(_FakeAdapter):
        def __init__(self, status_code):
            self.status_code = status_code

        def submit(self, context, query, access_token, idempotency_key):
            return httpx.Response(self.status_code, text="secret-provider-response")

    adapter = FailingAdapter(503)
    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), adapter))
    executor = DataSyncExecutor(factory, worker_id="retry-worker")
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "queued"
    assert refreshed.next_retry_at is not None
    assert "secret-provider-response" not in refreshed.failure_summary
    refreshed.next_retry_at = None
    session.commit()
    adapter.status_code = 422
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "failed"
    assert "secret-provider-response" not in refreshed.failure_summary


def test_runtime_refreshes_401_and_recovers_409(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="auth-recover",
        trace_id="trace-auth",
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    class RecoveringAdapter(_FakeAdapter):
        def __init__(self):
            super().__init__()
            self.submit_calls = 0

        def submit(self, context, query, access_token, idempotency_key):
            self.submit_calls += 1
            if self.submit_calls == 1:
                return httpx.Response(401)
            return httpx.Response(409)

        def recover_task(self, context, idempotency_key, access_token):
            return SubmitResult("external-recovered")

    adapter = RecoveringAdapter()
    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), adapter))
    executor = DataSyncExecutor(factory, worker_id="recovery-worker")
    calls = []
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    monkeypatch.setattr(executor._tokens, "invalidate", lambda *_args, **_kwargs: calls.append(1))
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "succeeded"
    assert refreshed.external_task_id == "external-recovered"
    assert adapter.submit_calls == 2
    assert len(calls) == 1


def test_unconfirmed_submit_replays_beyond_attempt_limit(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="lost-response",
        trace_id="trace-lost-response",
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    class ResponseLostAdapter(_FakeAdapter):
        def __init__(self):
            super().__init__()
            self.submissions = []

        def submit(self, context, query, access_token, idempotency_key):
            self.submissions.append((query, idempotency_key))
            if len(self.submissions) == 1:
                raise SyncRuntimeError(
                    "submit outcome unconfirmed", retryable=True, code="submit_unconfirmed"
                )
            return SubmitResult("existing-external-job", f"nexus-data-sync:{idempotency_key}")

    adapter = ResponseLostAdapter()
    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), adapter))
    executor = DataSyncExecutor(factory, worker_id="lost-response-worker", max_attempts=1)
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "queued"
    assert refreshed.failure_summary == "submit_unconfirmed"
    refreshed.next_retry_at = None
    session.commit()
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "succeeded"
    assert refreshed.external_task_id == "existing-external-job"
    assert adapter.submissions == [(plan.query_config, run.id)] * 2


def test_runtime_resumes_from_persisted_cursor_after_page_failure(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="cursor-recovery",
        trace_id="trace-cursor",
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    class PagedAdapter(_FakeAdapter):
        def __init__(self):
            super().__init__()
            self.seen_cursors = []
            self.fail_second = True

        def fetch_page(self, context, external_task_id, cursor, access_token):
            self.seen_cursors.append(cursor)
            if cursor == "next" and self.fail_second:
                self.fail_second = False
                return httpx.Response(503)
            return PageResult([{"id": cursor or "first"}], "next" if cursor is None else None)

    adapter = PagedAdapter()
    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), adapter))
    executor = DataSyncExecutor(factory, worker_id="cursor-worker")
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "queued"
    assert refreshed.last_cursor == "next"
    assert refreshed.processed_count == 1
    refreshed.next_retry_at = None
    session.commit()
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "succeeded"
    assert refreshed.processed_count == 2
    assert adapter.seen_cursors == [None, "next", "next"]


def test_pending_provider_status_does_not_exhaust_failure_attempts(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="pending-status",
        trace_id="trace-pending",
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    class PendingAdapter(_FakeAdapter):
        def get_status(self, context, external_task_id, access_token):
            return StatusResult("running")

    adapter = PendingAdapter()
    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), adapter))
    executor = DataSyncExecutor(factory, worker_id="pending-worker", max_attempts=1)
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "running"
    assert refreshed.attempt_count == 0


def test_external_paused_status_releases_worker_lease(session, monkeypatch):
    plan = _plan(session)
    run = create_manual_run(
        session, plan_id=plan.id, actor_id="admin", idempotency_key="external-pause",
        trace_id="trace-pause",
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    class PausedAdapter(_FakeAdapter):
        def get_status(self, context, external_task_id, access_token):
            return StatusResult("paused")

    monkeypatch.setattr("nexus_app.data_sync.runtime._provider_code", lambda _: (object(), PausedAdapter()))
    executor = DataSyncExecutor(factory, worker_id="pause-worker")
    monkeypatch.setattr(executor._tokens, "get_token", lambda *_: "token")
    assert executor.run_once()
    executor.close()
    session.expire_all()
    refreshed = session.get(models.DataSyncRun, run.id)
    assert refreshed.status == "paused"
    assert refreshed.claim_owner is None
    assert refreshed.lease_expires_at is None
