"""Creation and read model for provider-independent sync runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.data_sync.catalog import ProviderConfig, load_catalog
from nexus_app.enums import AuditEventType, DataSyncRunStatus


NONTERMINAL = (
    DataSyncRunStatus.QUEUED.value,
    DataSyncRunStatus.RUNNING.value,
    DataSyncRunStatus.PAUSED.value,
)


class RunError(ValueError):
    pass


class RunNotFound(RunError):
    pass


class RunConflict(RunError):
    pass


def _query_hash(query: dict) -> str:
    canonical = json.dumps(query, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_manual_run(
    session: Session, *, plan_id: str, actor_id: str, idempotency_key: str, trace_id: str,
) -> models.DataSyncRun:
    providers = load_catalog()
    plan = session.scalar(
        select(models.DataSyncConfig).where(models.DataSyncConfig.id == plan_id).with_for_update()
    )
    if plan is None:
        raise RunNotFound("sync plan not found")
    if plan.status != "active":
        raise RunConflict("sync plan is not active")
    existing = session.scalar(
        select(models.DataSyncRun).where(
            models.DataSyncRun.data_sync_config_id == plan_id,
            models.DataSyncRun.created_by == actor_id,
            models.DataSyncRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    active = session.scalar(
        select(models.DataSyncRun.id).where(
            models.DataSyncRun.data_sync_config_id == plan_id,
            models.DataSyncRun.status.in_(NONTERMINAL),
        )
    )
    if active is not None:
        raise RunConflict("sync plan already has a nonterminal run")
    provider = next((item for item in providers if item.provider_code == plan.provider_code), None)
    if provider is None or provider.status != "enabled":
        raise RunConflict("Provider is unavailable")
    snapshot = json.loads(json.dumps(plan.query_config))
    now = datetime.now(timezone.utc)
    run = models.DataSyncRun(
        data_sync_config_id=plan.id,
        provider_code=plan.provider_code,
        adapter_version=provider.adapter_version,
        status=DataSyncRunStatus.QUEUED.value,
        created_by=actor_id,
        idempotency_key=idempotency_key,
        query_snapshot=snapshot,
        query_hash=_query_hash(snapshot),
        queued_at=now,
        trace_id=trace_id,
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(models.DataSyncRun).where(
                models.DataSyncRun.data_sync_config_id == plan_id,
                models.DataSyncRun.created_by == actor_id,
                models.DataSyncRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        raise RunConflict("sync plan already has a nonterminal run") from exc
    write_audit(
        session, AuditEventType.DATA_SYNC_RUN_QUEUED, "data_sync_run", run.id, trace_id,
        {"plan_id": plan.id, "provider_code": plan.provider_code, "query_hash": run.query_hash},
        actor_type="user", actor_id=actor_id,
    )
    session.commit()
    session.refresh(run)
    return run


def create_scheduled_run(
    session: Session, *, plan_id: str, scheduled_slot: datetime, trace_id: str,
    providers: list[ProviderConfig] | None = None,
) -> models.DataSyncRun:
    if scheduled_slot.tzinfo is None or scheduled_slot.utcoffset() is None:
        raise RunError("scheduled_slot must include a timezone")
    providers = providers if providers is not None else load_catalog()
    plan = session.scalar(
        select(models.DataSyncConfig).where(models.DataSyncConfig.id == plan_id).with_for_update()
    )
    if plan is None:
        raise RunNotFound("sync plan not found")
    if plan.status != "active":
        raise RunConflict("sync plan is not active")
    slot = scheduled_slot.astimezone(timezone.utc)
    existing = session.scalar(select(models.DataSyncRun).where(
        models.DataSyncRun.data_sync_config_id == plan_id,
        models.DataSyncRun.scheduled_slot == slot,
    ))
    if existing is not None:
        return existing
    active = session.scalar(select(models.DataSyncRun.id).where(
        models.DataSyncRun.data_sync_config_id == plan_id,
        models.DataSyncRun.status.in_(NONTERMINAL),
    ))
    if active is not None:
        raise RunConflict("sync plan already has a nonterminal run")
    provider = next((item for item in providers if item.provider_code == plan.provider_code), None)
    if provider is None or provider.status != "enabled":
        raise RunConflict("Provider is unavailable")
    snapshot = json.loads(json.dumps(plan.query_config))
    run = models.DataSyncRun(
        data_sync_config_id=plan.id,
        provider_code=plan.provider_code,
        adapter_version=provider.adapter_version,
        status=DataSyncRunStatus.QUEUED.value,
        scheduled_slot=slot,
        query_snapshot=snapshot,
        query_hash=_query_hash(snapshot),
        queued_at=datetime.now(timezone.utc),
        trace_id=trace_id,
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(select(models.DataSyncRun).where(
            models.DataSyncRun.data_sync_config_id == plan_id,
            models.DataSyncRun.scheduled_slot == slot,
        ))
        if existing is not None:
            return existing
        raise RunConflict("sync plan already has a nonterminal run") from exc
    write_audit(
        session, AuditEventType.DATA_SYNC_RUN_QUEUED, "data_sync_run", run.id, trace_id,
        {"plan_id": plan.id, "provider_code": plan.provider_code, "query_hash": run.query_hash},
        actor_type="system",
    )
    session.commit()
    session.refresh(run)
    return run


def get_run(session: Session, run_id: str) -> models.DataSyncRun:
    run = session.get(models.DataSyncRun, run_id)
    if run is None:
        raise RunNotFound("sync run not found")
    return run


def list_runs(
    session: Session, *, provider_code: str | None = None,
    plan_id: str | None = None, status: DataSyncRunStatus | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    offset: int = 0, limit: int = 20,
) -> tuple[list[models.DataSyncRun], int]:
    filters = []
    if provider_code:
        filters.append(models.DataSyncRun.provider_code == provider_code)
    if plan_id:
        filters.append(models.DataSyncRun.data_sync_config_id == plan_id)
    if status:
        filters.append(models.DataSyncRun.status == status.value)
    if created_from:
        filters.append(models.DataSyncRun.created_at >= created_from)
    if created_to:
        filters.append(models.DataSyncRun.created_at <= created_to)
    total = session.scalar(select(func.count()).select_from(models.DataSyncRun).where(*filters)) or 0
    rows = list(session.scalars(
        select(models.DataSyncRun).where(*filters)
        .order_by(models.DataSyncRun.created_at.desc(), models.DataSyncRun.id.desc())
        .offset(offset).limit(limit)
    ))
    return rows, total
