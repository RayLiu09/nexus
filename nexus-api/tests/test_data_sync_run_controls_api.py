from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import AuditEventType, UserRole
from nexus_api.dependencies import require_user


def _run(client, key):
    plan = client.post(
        "/internal/v1/data-sync/plans",
        headers={"Idempotency-Key": f"plan-{key}"},
        json={
            "name": "Control plan", "provider_code": "mock",
            "frequency": "1_month", "query_config": {"keyword": "controls"},
        },
    )
    assert plan.status_code == 201
    run = client.post(
        f"/internal/v1/data-sync/plans/{plan.json()['data']['id']}/runs",
        headers={"Idempotency-Key": f"run-{key}"},
    )
    assert run.status_code == 201
    return run.json()["data"]["id"]


def _control(client, run_id, action, key):
    return client.post(
        f"/internal/v1/data-sync/runs/{run_id}/{action}",
        headers={"Idempotency-Key": key},
    )


def test_sync_pause_resume_cancel_and_replay(app, session, monkeypatch):
    from nexus_app.data_sync import controls
    from nexus_app.data_sync.tokens import TokenManager

    calls = []

    class Adapter:
        def pause(self, provider, task_id, token, key):
            assert not session.in_transaction()
            calls.append(("pause", key))
            return {"request_id": "pause-ack"}

        def resume(self, provider, task_id, token, key):
            assert not session.in_transaction()
            calls.append(("resume", key))
            return {"request_id": "resume-ack"}

        def cancel(self, provider, task_id, token, key):
            assert not session.in_transaction()
            calls.append(("cancel", key))
            return {"request_id": "cancel-ack"}

    monkeypatch.setattr(controls, "_provider_code", lambda _: (object(), Adapter()))
    monkeypatch.setattr(TokenManager, "get_token", lambda *_: "token")
    with TestClient(app) as client:
        run_id = _run(client, "lifecycle")
        run = session.get(models.DataSyncRun, run_id)
        run.status = "running"
        run.external_task_id = "external-1"
        run.claim_owner = "old-worker"
        session.commit()
        paused = _control(client, run_id, "pause", "pause-1")
        assert paused.status_code == 200
        assert paused.json()["data"]["status"] == "paused"
        assert session.get(models.DataSyncRun, run_id).claim_owner is None
        assert _control(client, run_id, "pause", "pause-1").status_code == 200
        assert _control(client, run_id, "resume", "pause-1").status_code == 409
        resumed = _control(client, run_id, "resume", "resume-1")
        assert resumed.status_code == 200
        assert resumed.json()["data"]["status"] == "running"
        from nexus_app.data_sync.runtime import claim_run
        assert claim_run(session, "new-worker").id == run_id
        assert _control(client, run_id, "pause", "pause-1").json()["data"]["status"] == "running"
        cancelled = _control(client, run_id, "cancel", "cancel-1")
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "cancelled"
        assert _control(client, run_id, "cancel", "cancel-1").status_code == 200
        assert _control(client, run_id, "resume", "resume-2").status_code == 409
        assert _control(client, "missing", "cancel", "missing-key").status_code == 404
    assert calls == [("pause", "pause-1"), ("resume", "resume-1"), ("cancel", "cancel-1")]
    audits = list(session.scalars(select(models.AuditLog).where(
        models.AuditLog.target_id == run_id,
        models.AuditLog.event_type == AuditEventType.DATA_SYNC_RUN_CONTROLLED,
    )))
    assert len(audits) == 3
    assert all(row.actor_id == "user-test-admin" and row.trace_id for row in audits)
    assert all("pause-1" not in str(row.summary) and "token" not in str(row.summary) for row in audits)


def test_queued_cancel_is_local_and_requires_admin(app, session, stub_user):
    with TestClient(app) as client:
        run_id = _run(client, "queued")
        assert _control(client, run_id, "pause", "pause-queued").status_code == 409
        assert _control(client, run_id, "cancel", "cancel-queued").json()["data"]["status"] == "cancelled"
        assert session.get(models.DataSyncRun, run_id).external_task_id is None
        assert _control(client, run_id, "cancel", "cancel-queued").status_code == 200
        assert _control(client, run_id, "cancel", "new-key").status_code == 409
        assert client.post(f"/internal/v1/data-sync/runs/{run_id}/cancel").status_code == 428
        stub_user.role = UserRole.BUSINESS_EXPERT
        app.dependency_overrides[require_user] = lambda: stub_user
        assert _control(client, run_id, "cancel", "forbidden").status_code == 403


def test_crawler_pause_ack_waits_for_external_paused_state(app, session, monkeypatch):
    from nexus_app.data_sync import controls
    from nexus_app.data_sync.tokens import TokenManager

    class Adapter:
        result_handler = object()

        def pause(self, provider, task_id, token, key):
            assert not session.in_transaction()
            return {"state": "pausing", "desired_state": "paused"}

    monkeypatch.setattr(controls, "_provider_code", lambda _: (object(), Adapter()))
    monkeypatch.setattr(TokenManager, "get_token", lambda *_: "token")
    with TestClient(app) as client:
        run_id = _run(client, "crawler-pausing")
        run = session.get(models.DataSyncRun, run_id)
        run.status = "running"
        run.external_task_id = "external-pausing"
        session.commit()
        paused = _control(client, run_id, "pause", "pause-crawler")
        assert paused.status_code == 200
        assert paused.json()["data"]["status"] == "running"
        assert paused.json()["data"]["external_status"] == "pausing"
        assert session.get(models.DataSyncRun, run_id).status_detail["desired_state"] == "paused"


def test_crawler_stable_pause_ack_updates_external_state(app, session, monkeypatch):
    from nexus_app.data_sync import controls
    from nexus_app.data_sync.tokens import TokenManager

    class Adapter:
        result_handler = object()

        def pause(self, provider, task_id, token, key):
            assert not session.in_transaction()
            return {"state": "paused", "desired_state": "paused"}

    monkeypatch.setattr(controls, "_provider_code", lambda _: (object(), Adapter()))
    monkeypatch.setattr(TokenManager, "get_token", lambda *_: "token")
    with TestClient(app) as client:
        run_id = _run(client, "crawler-stable-pause")
        run = session.get(models.DataSyncRun, run_id)
        run.status = "running"
        run.external_status = "queued"
        run.external_task_id = "external-paused"
        session.commit()
        paused = _control(client, run_id, "pause", "pause-crawler-stable")
        assert paused.status_code == 200
        assert paused.json()["data"]["status"] == "paused"
        assert paused.json()["data"]["external_status"] == "paused"
        assert session.get(models.DataSyncRun, run_id).status_detail["desired_state"] == "paused"


def test_failed_downstream_control_keeps_state_and_can_retry_key(app, session, monkeypatch):
    from nexus_app.data_sync import controls
    from nexus_app.data_sync.runtime import SyncRuntimeError
    from nexus_app.data_sync.tokens import TokenManager

    class Adapter:
        fail = True

        def pause(self, provider, task_id, token, key):
            assert not session.in_transaction()
            if self.fail:
                raise SyncRuntimeError("tenant-key-secret", retryable=True, code="http_503")
            return {"request_id": "pause-ack"}

    adapter = Adapter()
    monkeypatch.setattr(controls, "_provider_code", lambda _: (object(), adapter))
    monkeypatch.setattr(TokenManager, "get_token", lambda *_: "token")
    with TestClient(app) as client:
        run_id = _run(client, "failure")
        run = session.get(models.DataSyncRun, run_id)
        run.status = "running"
        run.external_task_id = "external-2"
        session.commit()
        failed = _control(client, run_id, "pause", "retry-pause")
        assert failed.status_code == 503
        session.expire_all()
        run = session.get(models.DataSyncRun, run_id)
        assert run.status == "running"
        assert run.failure_summary == "control:http_503"
        assert "tenant-key-secret" not in str(run.failure_summary)
        adapter.fail = False
        assert _control(client, run_id, "pause", "retry-pause").json()["data"]["status"] == "paused"
    audits = list(session.scalars(select(models.AuditLog).where(
        models.AuditLog.target_id == run_id,
        models.AuditLog.event_type == AuditEventType.DATA_SYNC_RUN_CONTROLLED,
    )))
    assert [row.summary["outcome"] for row in audits] == ["failed", "succeeded"]
    assert all("tenant-key-secret" not in str(row.summary) for row in audits)


def test_control_records_key_when_worker_reaches_target_first(app, session, monkeypatch):
    from nexus_app.data_sync import controls
    from nexus_app.data_sync.tokens import TokenManager

    class Adapter:
        def pause(self, provider, task_id, token, key):
            assert not session.in_transaction()
            session.get(models.DataSyncRun, task_id).status = "paused"
            session.commit()
            return {"request_id": "pause-ack"}

    monkeypatch.setattr(controls, "_provider_code", lambda _: (object(), Adapter()))
    monkeypatch.setattr(TokenManager, "get_token", lambda *_: "token")
    with TestClient(app) as client:
        run_id = _run(client, "worker-race")
        run = session.get(models.DataSyncRun, run_id)
        run.status = "running"
        run.external_task_id = run_id
        session.commit()
        assert _control(client, run_id, "pause", "race-pause").json()["data"]["status"] == "paused"
        assert _control(client, run_id, "pause", "race-pause").status_code == 200
    audits = list(session.scalars(select(models.AuditLog).where(
        models.AuditLog.target_id == run_id,
        models.AuditLog.event_type == AuditEventType.DATA_SYNC_RUN_CONTROLLED,
    )))
    assert len(audits) == 1
    assert audits[0].summary["outcome"] == "succeeded"


def test_control_returns_conflict_when_run_finishes_during_downstream_call(app, session, monkeypatch):
    from nexus_app.data_sync import controls
    from nexus_app.data_sync.tokens import TokenManager

    class Adapter:
        def pause(self, provider, task_id, token, key):
            assert not session.in_transaction()
            session.get(models.DataSyncRun, task_id).status = "succeeded"
            session.commit()
            return {"request_id": "pause-ack"}

    monkeypatch.setattr(controls, "_provider_code", lambda _: (object(), Adapter()))
    monkeypatch.setattr(TokenManager, "get_token", lambda *_: "token")
    with TestClient(app) as client:
        run_id = _run(client, "terminal-race")
        run = session.get(models.DataSyncRun, run_id)
        run.status = "running"
        run.external_task_id = run_id
        session.commit()
        assert _control(client, run_id, "pause", "terminal-pause").status_code == 409
    session.expire_all()
    assert session.get(models.DataSyncRun, run_id).status == "succeeded"
    audit = session.scalar(select(models.AuditLog).where(
        models.AuditLog.target_id == run_id,
        models.AuditLog.event_type == AuditEventType.DATA_SYNC_RUN_CONTROLLED,
    ))
    assert audit.summary["outcome"] == "failed"
    assert audit.summary["error_code"] == "status_changed"
