from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.auth_service import generate_api_caller_key, hash_api_caller_key
from nexus_app.enums import AuditEventType

ModelT = TypeVar("ModelT")


@dataclass
class ApiCallerMintResult:
    """Returned by `create_api_caller` so the route can surface the plaintext
    key to the operator exactly once. `caller_key_plaintext` is None for
    legacy (caller-supplied) keys — the caller already has it."""
    caller: "models.ApiCaller"
    caller_key_plaintext: str | None


class ResourceNotFoundError(Exception):
    def __init__(self, resource_name: str) -> None:
        super().__init__(f"{resource_name} not found")
        self.resource_name = resource_name


def list_rows(
    session: Session,
    model: type[ModelT],
    *,
    limit: int | None = None,
    offset: int | None = None,
    filters: dict[str, Any] | None = None,
) -> list[ModelT]:
    """Ordered list of rows. `limit`/`offset` enable pagination at the SQL
    layer so unbounded result sets can never reach the response serializer.
    Both `None` (backward compat) returns the full table.
    Optional `filters` dict maps column names to equality values."""
    stmt = select(model).order_by(model.created_at.desc())
    if filters:
        for col_name, value in filters.items():
            if value is not None:
                col = getattr(model, col_name, None)
                if col is not None:
                    stmt = stmt.where(col == value)
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def count_rows(
    session: Session,
    model: type[ModelT],
    filters: dict[str, Any] | None = None,
) -> int:
    """Total row count for `model`. Pairs with `list_rows` so the response
    `meta.total` reflects the underlying table size, not just the returned
    slice — required for client-side pagination UI.
    Optional `filters` dict maps column names to equality values."""
    stmt = select(func.count()).select_from(model)
    if filters:
        for col_name, value in filters.items():
            if value is not None:
                col = getattr(model, col_name, None)
                if col is not None:
                    stmt = stmt.where(col == value)
    return int(session.scalar(stmt) or 0)


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
    """Legacy single-return signature. Mints/stores caller exactly like
    `mint_api_caller` but discards the plaintext, since callers using this
    signature always supplied their own `caller_key`."""
    result = mint_api_caller(
        session,
        payload,
        trace_id=trace_id,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    return result.caller


def mint_api_caller(
    session: Session,
    payload,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> ApiCallerMintResult:
    """Create an ApiCaller and audit it.

    Behavior keyed off whether the caller supplied `caller_key`:
      * Supplied (legacy path): store the plaintext + its hash; return
        plaintext=None because the caller already has the key.
      * Omitted (recommended): mint a fresh key server-side; persist ONLY the
        hash and return the plaintext exactly once so the route can surface it.
    """
    data: dict[str, Any] = payload.model_dump()
    provided_key = data.pop("caller_key", None)

    plaintext: str | None
    if provided_key:
        plaintext = None  # caller supplied it; no need to echo back
        caller_key_to_store = provided_key
        caller_key_hash = hash_api_caller_key(provided_key)
    else:
        plaintext = generate_api_caller_key()
        # The full plaintext is returned once in caller_key_plaintext and never persisted.
        caller_key_to_store = None
        caller_key_hash = hash_api_caller_key(plaintext)

    row = models.ApiCaller(
        caller_key=caller_key_to_store,
        caller_key_hash=caller_key_hash,
        **data,
    )
    session.add(row)
    session.flush()
    write_audit(
        session,
        AuditEventType.API_CALLER_CREATED,
        "api_caller",
        row.id,
        trace_id,
        {
            "name": row.name,
            "org_scope": row.org_scope,
            "key_source": "server_minted" if plaintext else "client_supplied",
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.commit()
    session.refresh(row)
    return ApiCallerMintResult(caller=row, caller_key_plaintext=plaintext)


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
