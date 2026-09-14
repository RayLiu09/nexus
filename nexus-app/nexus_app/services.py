from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.api_permissions import OPEN_API_FULL_ACCESS_SCOPES
from nexus_app.audit import write_audit
from nexus_app.auth_service import (
    generate_api_caller_key,
    hash_api_caller_key,
    hash_password,
)
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


class DuplicateUsernameError(Exception):
    """Raised by `create_user` when the requested username already exists."""

    def __init__(self, username: str) -> None:
        super().__init__(f"username '{username}' already exists")
        self.username = username


def _summarize_user(row: "models.UserAccount") -> dict[str, Any]:
    return {
        "username": row.username,
        "display_name": row.display_name,
        "role": row.role.value if hasattr(row.role, "value") else str(row.role),
        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
    }


def create_user(
    session: Session,
    payload,
    *,
    trace_id: str | None = None,
) -> models.UserAccount:
    """Create a console user. Password is bcrypt-hashed; audit event emitted."""
    data: dict[str, Any] = payload.model_dump()
    password = data.pop("password")
    # Username uniqueness check — do it before insert so we can raise a typed
    # error instead of leaking an IntegrityError to the route layer.
    existing = session.scalar(
        select(models.UserAccount).where(models.UserAccount.username == data["username"])
    )
    if existing is not None:
        raise DuplicateUsernameError(data["username"])

    row = models.UserAccount(**data, password_hash=hash_password(password))
    session.add(row)
    session.flush()
    write_audit(
        session,
        AuditEventType.USER_CREATED,
        target_type="user_account",
        target_id=row.id,
        trace_id=trace_id,
        summary=_summarize_user(row),
    )
    session.commit()
    session.refresh(row)
    return row


def update_user(
    session: Session,
    user_id: str,
    payload,
    *,
    trace_id: str | None = None,
) -> models.UserAccount:
    """Partial update. Fields set to None on the payload are treated as
    "not provided" (Pydantic default) and skipped."""
    row = session.get(models.UserAccount, user_id)
    if row is None:
        raise ResourceNotFoundError("user_account")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return row

    changed: dict[str, tuple[Any, Any]] = {}
    status_before = row.status
    for field, new_value in updates.items():
        current = getattr(row, field)
        if current != new_value:
            changed[field] = (current, new_value)
            setattr(row, field, new_value)

    if not changed:
        return row

    session.flush()

    if "status" in changed:
        write_audit(
            session,
            AuditEventType.USER_STATUS_CHANGED,
            target_type="user_account",
            target_id=row.id,
            trace_id=trace_id,
            summary={
                "username": row.username,
                "status_before": (
                    status_before.value
                    if hasattr(status_before, "value")
                    else str(status_before)
                ),
                "status_after": (
                    row.status.value if hasattr(row.status, "value") else str(row.status)
                ),
            },
        )

    non_status = {k: v for k, v in changed.items() if k != "status"}
    if non_status:
        write_audit(
            session,
            AuditEventType.USER_UPDATED,
            target_type="user_account",
            target_id=row.id,
            trace_id=trace_id,
            summary={
                "username": row.username,
                "changed_fields": sorted(non_status.keys()),
            },
        )

    session.commit()
    session.refresh(row)
    return row


def reset_user_password(
    session: Session,
    user_id: str,
    new_password: str,
    *,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.UserAccount:
    """Reset a user's login password. Called by:
      • admin flow (POST /users/{id}/password) — actor_* omitted;
      • self-service flow (POST /users/me/change-password) — actor_type='user',
        actor_id=current_user.id, so the audit row records who performed it.
    Always clears the brute-force lockout counters so the target user can log
    in immediately with the new credential."""
    row = session.get(models.UserAccount, user_id)
    if row is None:
        raise ResourceNotFoundError("user_account")

    row.password_hash = hash_password(new_password)
    row.failed_login_count = 0
    row.lockout_until = None
    session.flush()
    write_audit(
        session,
        AuditEventType.USER_PASSWORD_RESET,
        target_type="user_account",
        target_id=row.id,
        trace_id=trace_id,
        summary={
            "username": row.username,
            "self_service": actor_id == row.id,
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )
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
    # Every P0 API Caller is a credential for the complete public `/open/v1/*`
    # surface. Do not persist arbitrary UI labels that do not map to route
    # authorization; future restricted scopes need an explicit route policy.
    data["permission_scope"] = list(OPEN_API_FULL_ACCESS_SCOPES)

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
            "permission_scope": row.permission_scope,
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
