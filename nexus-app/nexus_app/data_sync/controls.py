"""Synchronous, idempotent controls for data sync runs."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.data_sync.runtime import _invoke_with_token, _provider_code, _set_status, SyncRuntimeError
from nexus_app.data_sync.tokens import TokenError, TokenManager
from nexus_app.enums import AuditEventType


class ControlError(ValueError):
    pass


class ControlNotFound(ControlError):
    pass


class ControlConflict(ControlError):
    pass


class ControlUnavailable(ControlError):
    pass


_TARGET = {"pause": "paused", "resume": "running", "cancel": "cancelled"}
_ALLOWED = {"pause": {"running"}, "resume": {"paused"}, "cancel": {"queued", "running", "paused"}}
_TERMINAL = {"succeeded", "partially_succeeded", "failed", "cancelled"}


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _previous_action(session: Session, run_id: str, actor_id: str, digest: str) -> tuple[str, str] | None:
    rows = session.scalars(select(models.AuditLog).where(
        models.AuditLog.target_type == "data_sync_run",
        models.AuditLog.target_id == run_id,
        models.AuditLog.actor_id == actor_id,
        models.AuditLog.event_type == AuditEventType.DATA_SYNC_RUN_CONTROLLED,
    ))
    previous = None
    for row in rows:
        if row.summary.get("idempotency_key_hash") == digest:
            previous = row.summary["action"], row.summary["outcome"]
            if previous[1] == "succeeded":
                return previous
    return previous


def _write_control_audit(
    session: Session, run: models.DataSyncRun, *, action: str, actor_id: str,
    trace_id: str, digest: str, outcome: str, error_code: str | None = None,
) -> None:
    summary = {"action": action, "outcome": outcome, "idempotency_key_hash": digest}
    if error_code:
        summary["error_code"] = error_code
    write_audit(
        session, AuditEventType.DATA_SYNC_RUN_CONTROLLED, "data_sync_run", run.id,
        trace_id, summary, actor_type="user", actor_id=actor_id,
    )


def control_run(
    session: Session, *, run_id: str, action: str, actor_id: str,
    idempotency_key: str, trace_id: str,
) -> models.DataSyncRun:
    if action not in _TARGET:
        raise ControlError("unsupported run control")
    digest = _key_hash(idempotency_key)
    run = session.get(models.DataSyncRun, run_id)
    if run is None:
        raise ControlNotFound("sync run not found")
    previous = _previous_action(session, run_id, actor_id, digest)
    if previous is not None:
        if previous[0] != action:
            raise ControlConflict("Idempotency-Key was used for a different control")
        if previous[1] == "succeeded":
            return run
    if run.status in _TERMINAL or run.status not in _ALLOWED[action]:
        raise ControlConflict("run cannot be controlled in its current state")
    provider_code = run.provider_code
    external_task_id = run.external_task_id
    expected_status = run.status
    session.rollback()

    if external_task_id is None and action != "cancel":
        raise ControlConflict("run has no external task")
    if external_task_id is None and expected_status != "queued":
        raise ControlConflict("run has no external task")

    control_result = None
    has_result_handler = False
    if external_task_id is not None:
        try:
            provider, adapter = _provider_code(provider_code)
            method = getattr(adapter, action, None)
            if not callable(method):
                raise SyncRuntimeError("control unsupported", code="control_unsupported")
            has_result_handler = getattr(adapter, "result_handler", None) is not None
            with httpx.Client(timeout=30.0) as client:
                tokens = TokenManager(client)
                control_result = _invoke_with_token(
                    tokens, provider, adapter,
                    lambda token: method(provider, external_task_id, token, idempotency_key),
                )
        except Exception as exc:
            error_code = getattr(exc, "code", "control_unavailable")
            if not isinstance(error_code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", error_code):
                error_code = "control_unavailable"
            with session.begin():
                run = session.scalar(select(models.DataSyncRun).where(
                    models.DataSyncRun.id == run_id,
                ).with_for_update())
                if run is not None:
                    run.last_control_action = action
                    run.last_control_operator_id = actor_id
                    run.last_control_requested_at = datetime.now(timezone.utc)
                    run.failure_summary = f"control:{error_code}"
                    _write_control_audit(
                        session, run, action=action, actor_id=actor_id,
                        trace_id=trace_id, digest=digest, outcome="failed", error_code=error_code,
                    )
            raise ControlUnavailable("Provider control failed") from exc

    external_state = control_result.get("state") if isinstance(control_result, dict) else None
    desired_state = control_result.get("desired_state") if isinstance(control_result, dict) else None
    pending = external_state in {"pausing", "cancelling"} or (
        has_result_handler and action == "cancel" and external_state == "cancelled"
    )

    conflict = False
    with session.begin():
        run = session.scalar(select(models.DataSyncRun).where(
            models.DataSyncRun.id == run_id,
        ).with_for_update())
        if run is None:
            raise ControlNotFound("sync run not found")
        previous = _previous_action(session, run_id, actor_id, digest)
        if previous is not None and previous[1] == "succeeded":
            return run
        if run.status != expected_status:
            if run.status == _TARGET[action]:
                run.last_control_action = action
                run.last_control_operator_id = actor_id
                run.last_control_requested_at = datetime.now(timezone.utc)
                _write_control_audit(
                    session, run, action=action, actor_id=actor_id,
                    trace_id=trace_id, digest=digest, outcome="succeeded",
                )
                return run
            conflict = True
            run.failure_summary = "control:status_changed"
            _write_control_audit(
                session, run, action=action, actor_id=actor_id,
                trace_id=trace_id, digest=digest, outcome="failed", error_code="status_changed",
            )
        else:
            if pending:
                if run.status == "paused":
                    _set_status(session, run, "running", reason=f"user_{action}_accepted")
                    run.claim_owner = None
                    run.lease_expires_at = None
                    run.heartbeat_at = None
            else:
                _set_status(session, run, _TARGET[action], reason=f"user_{action}")
            if external_state is not None:
                run.external_status = external_state
                run.status_detail = {"desired_state": desired_state}
            run.last_control_action = action
            run.last_control_operator_id = actor_id
            run.last_control_requested_at = datetime.now(timezone.utc)
            run.failure_summary = None
            if not pending and action in {"pause", "cancel"}:
                run.claim_owner = None
                run.lease_expires_at = None
                run.heartbeat_at = None
            if action == "cancel" and not pending:
                run.finished_at = datetime.now(timezone.utc)
            _write_control_audit(
                session, run, action=action, actor_id=actor_id,
                trace_id=trace_id, digest=digest, outcome="succeeded",
            )
    if conflict:
        raise ControlConflict("run state changed while control was sent")
    session.refresh(run)
    return run
