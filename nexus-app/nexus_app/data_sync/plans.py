"""Immutable API data sync plans and audited lifecycle controls."""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.data_sync.catalog import _load_adapter, load_catalog
from nexus_app.enums import AuditEventType


class PlanError(ValueError):
    pass


class PlanNotFound(PlanError):
    pass


class PlanConflict(PlanError):
    pass


_MONTHS = {"1_month": 1, "3_months": 3, "6_months": 6, "9_months": 9, "1_year": 12}


def next_run_time(start: datetime, frequency: str) -> datetime:
    months = _MONTHS[frequency]
    month_index = start.year * 12 + start.month - 1 + months
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _request_hash(name: str, provider_code: str, frequency: str, query: dict[str, Any]) -> str:
    payload = {"name": name, "provider_code": provider_code, "frequency": frequency, "query": query}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def create_plan(
    session: Session,
    *,
    name: str,
    provider_code: str,
    frequency: str,
    query_config: dict[str, Any],
    actor_id: str,
    idempotency_key: str,
    trace_id: str,
) -> models.DataSyncConfig:
    if frequency not in _MONTHS:
        raise PlanError("unsupported frequency")
    provider = next((item for item in load_catalog() if item.provider_code == provider_code), None)
    if provider is None or provider.status != "enabled":
        raise PlanError("Provider is unavailable")
    try:
        normalized_query = _load_adapter(provider.adapter_factory).validate_query(query_config)
    except ValidationError as exc:
        raise PlanError("query_config is invalid for this Provider") from exc
    if not isinstance(normalized_query, dict):
        raise PlanError("Provider query validation must return an object")
    digest = _request_hash(name, provider_code, frequency, normalized_query)
    existing = session.scalar(
        select(models.DataSyncConfig).where(
            models.DataSyncConfig.created_by == actor_id,
            models.DataSyncConfig.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != digest:
            raise PlanConflict("Idempotency-Key was used for a different sync plan")
        return existing
    now = datetime.now(timezone.utc)
    plan = models.DataSyncConfig(
        name=name,
        provider_code=provider_code,
        frequency=frequency,
        query_config=normalized_query,
        status="active",
        next_run_at=next_run_time(now, frequency),
        created_by=actor_id,
        updated_by=actor_id,
        idempotency_key=idempotency_key,
        request_hash=digest,
    )
    session.add(plan)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(models.DataSyncConfig).where(
                models.DataSyncConfig.created_by == actor_id,
                models.DataSyncConfig.idempotency_key == idempotency_key,
            )
        )
        if existing is not None and existing.request_hash == digest:
            return existing
        raise PlanConflict("Idempotency-Key was used for a different sync plan") from exc
    write_audit(
        session, AuditEventType.DATA_SYNC_PLAN_CREATED, "data_sync_config", plan.id,
        trace_id, {"provider_code": provider_code, "frequency": frequency},
        actor_type="user", actor_id=actor_id,
    )
    session.commit()
    session.refresh(plan)
    return plan


def get_plan(session: Session, plan_id: str) -> models.DataSyncConfig:
    plan = session.get(models.DataSyncConfig, plan_id)
    if plan is None:
        raise PlanNotFound("sync plan not found")
    return plan


def list_plans(session: Session, *, include_deleted: bool = False) -> list[models.DataSyncConfig]:
    statement = select(models.DataSyncConfig)
    if not include_deleted:
        statement = statement.where(models.DataSyncConfig.status != "deleted")
    return list(session.scalars(statement.order_by(models.DataSyncConfig.created_at.desc())))


def change_plan_status(
    session: Session, plan_id: str, *, action: str, actor_id: str, trace_id: str,
) -> models.DataSyncConfig:
    if action not in {"pause", "resume", "delete"}:
        raise PlanError("unsupported plan action")
    plan = session.scalar(
        select(models.DataSyncConfig).where(models.DataSyncConfig.id == plan_id).with_for_update()
    )
    if plan is None:
        raise PlanNotFound("sync plan not found")
    target = {"pause": "paused", "resume": "active", "delete": "deleted"}[action]
    if plan.status == target:
        return plan
    if plan.status == "deleted":
        raise PlanConflict("deleted sync plan cannot be changed")
    if action == "delete":
        active_run = session.scalar(
            select(models.DataSyncRun.id).where(
                models.DataSyncRun.data_sync_config_id == plan_id,
                models.DataSyncRun.status.in_(("queued", "running", "paused")),
            )
        )
        if active_run is not None:
            raise PlanConflict("sync plan has a nonterminal run")
    now = datetime.now(timezone.utc)
    plan.status = target
    plan.updated_by = actor_id
    if action == "pause":
        plan.next_run_at = None
    elif action == "resume":
        plan.next_run_at = next_run_time(now, plan.frequency)
    else:
        plan.next_run_at = None
        plan.deleted_at = now
    event = {
        "pause": AuditEventType.DATA_SYNC_PLAN_PAUSED,
        "resume": AuditEventType.DATA_SYNC_PLAN_RESUMED,
        "delete": AuditEventType.DATA_SYNC_PLAN_DELETED,
    }[action]
    write_audit(
        session, event, "data_sync_config", plan.id, trace_id,
        {"provider_code": plan.provider_code, "status": target},
        actor_type="user", actor_id=actor_id,
    )
    session.commit()
    session.refresh(plan)
    return plan
