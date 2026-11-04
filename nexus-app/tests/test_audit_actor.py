"""Attribution is bound by execution context, never guessed from event names."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from nexus_app.audit import audit_actor, write_audit
from nexus_app.enums import AuditEventType


def _write(session, **identity):
    return write_audit(
        session, AuditEventType.PIPELINE_FAILED, "job", "job-test", "trace-test",
        {"api_key": "private", "reason": "test"}, **identity,
    )


def test_nested_scope_restores_after_failure_and_keeps_redaction(session):
    with audit_actor("user", "admin"):
        with pytest.raises(RuntimeError):
            with audit_actor("system", "worker-a"):
                row = _write(session)
                assert (row.actor_type, row.actor_id) == ("system", "worker-a")
                assert row.summary["api_key"] == "***redacted***"
                assert row.trace_id == "trace-test"
                raise RuntimeError("job failed")
        row = _write(session)
        assert (row.actor_type, row.actor_id) == ("user", "admin")
    row = _write(session)
    assert (row.actor_type, row.actor_id) == (None, None)


@pytest.mark.parametrize(("explicit", "expected"), [
    ({}, ("system", "worker-a")),
    ({"actor_type": "system"}, ("system", "worker-a")),
    ({"actor_type": "user", "actor_id": "admin"}, ("user", "admin")),
    ({"actor_type": "api_caller", "actor_id": "caller"}, ("api_caller", "caller")),
    ({"actor_type": "system", "actor_id": "repair"}, ("system", "repair")),
    ({"actor_id": "legacy-user"}, (None, "legacy-user")),
    ({"actor_type": "user"}, ("user", None)),
])
def test_explicit_identity_takes_precedence_without_cross_actor_merging(session, explicit, expected):
    with audit_actor("system", "worker-a"):
        row = _write(session, **explicit)
    assert (row.actor_type, row.actor_id) == expected


@pytest.mark.parametrize("event", [AuditEventType.USER_LOGIN_FAILED, AuditEventType.TOKEN_REFRESH_FAILED])
def test_unknown_authentication_events_remain_unknown(session, event):
    row = write_audit(session, event, "user", "unknown", None, {})
    assert row.actor_type is None
    assert row.actor_id is None


def test_scopes_are_isolated_across_threads_and_do_not_leak_to_pool_reuse():
    # Sessions are deliberately not shared across threads. Only persisted actor
    # arguments are observed here; database integration is covered separately.
    sink = SimpleNamespace(add=lambda _: None, flush=lambda: None)
    barrier = Barrier(2)

    def task(actor_id):
        with audit_actor("system", actor_id):
            barrier.wait(timeout=5)
            row = _write(sink)
            return row.actor_type, row.actor_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(task, name) for name in ("worker-a", "worker-b")]
        assert [f.result() for f in futures] == [("system", "worker-a"), ("system", "worker-b")]
        row = pool.submit(_write, sink).result()
        assert (row.actor_type, row.actor_id) == (None, None)


def test_scopes_are_isolated_across_async_tasks():
    sink = SimpleNamespace(add=lambda _: None, flush=lambda: None)

    async def task(actor_id):
        with audit_actor("system", actor_id):
            await asyncio.sleep(0)
            row = _write(sink)
            return row.actor_id

    async def run():
        assert await asyncio.gather(task("worker-a"), task("worker-b")) == ["worker-a", "worker-b"]
        assert _write(sink).actor_id is None

    asyncio.run(run())
