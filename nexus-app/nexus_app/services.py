from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType

ModelT = TypeVar("ModelT")


class ResourceNotFoundError(Exception):
    def __init__(self, resource_name: str) -> None:
        super().__init__(f"{resource_name} not found")
        self.resource_name = resource_name


def list_rows(session: Session, model: type[ModelT]) -> list[ModelT]:
    return list(session.scalars(select(model).order_by(model.created_at.desc())).all())


def get_row(session: Session, model: type[ModelT], row_id: str, resource_name: str) -> ModelT:
    row = session.get(model, row_id)
    if row is None:
        raise ResourceNotFoundError(resource_name)
    return row


def create_org_unit(session: Session, payload) -> models.OrgUnit:
    row = models.OrgUnit(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_user(session: Session, payload) -> models.UserAccount:
    row = models.UserAccount(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_api_caller(
    session: Session,
    payload,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.ApiCaller:
    row = models.ApiCaller(**payload.model_dump())
    session.add(row)
    session.flush()
    write_audit(
        session,
        AuditEventType.API_CALLER_CREATED,
        "api_caller",
        row.id,
        trace_id,
        {"name": row.name, "org_scope": row.org_scope},
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.commit()
    session.refresh(row)
    return row


def create_data_source(
    session: Session,
    payload,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.DataSource:
    row = models.DataSource(**payload.model_dump())
    session.add(row)
    session.flush()

    hints = row.default_governance_hints or {}
    level = hints.get("level")
    summary: dict[str, Any] = {
        "code": row.code,
        "source_type": row.source_type.value,
        "status": row.status.value,
    }
    if level:
        summary["default_level"] = level
    if level in {"L3", "L4"}:
        # L1/L2 is the P0 default; L3/L4 is an exception that must carry approval evidence.
        summary["level_elevated"] = True
        summary["approval_evidence"] = hints.get("approval_evidence")

    write_audit(
        session,
        AuditEventType.DATA_SOURCE_CREATED,
        "data_source",
        row.id,
        trace_id,
        summary,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.commit()
    session.refresh(row)
    return row


def create_ingest_batch(session: Session, payload) -> models.IngestBatch:
    row = models.IngestBatch(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_raw_object(session: Session, payload) -> models.RawObject:
    row = models.RawObject(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
