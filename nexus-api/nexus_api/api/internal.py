"""Internal console control-plane API (`/internal/v1/*`).

Mounted with a router-level `Depends(require_user)` so every request requires a
valid JWT — issued via `/internal/v1/auth/login`. The auth endpoints themselves
(`/auth/login`, `/auth/refresh`, `/auth/logout`) opt out of the dependency by
declaring `dependencies=[]` at the decorator level.

Endpoints here back the nexus-console UI: identity, data sources, ingest,
raw objects, jobs, assets/versions (full state), parse artifacts, normalized
refs, audit logs, AI prompt profiles & governance runs, governance results
(view=full|operator|public — view chosen by caller's role), governance rules
admin, and manual version restart.

Strictly out of scope: anything consumed by upstream applications — that lives
in `/open/v1/*` (see `open.py`).
"""
import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import require_user
from nexus_api.responses import list_response, response
from nexus_app import auth_service, models, pipeline, schemas as domain_schemas, services
from nexus_app.ai_governance.rules_registry import (
    GovernanceRulesRegistry,
    RulesEtagMismatchError,
    get_governance_rules_registry,
)
from nexus_app.ai_governance.services import (
    AIGovernanceError,
    AIGovernanceService,
    PromptProfileNotFoundError,
    PromptProfileService,
)
from nexus_app.audit import write_audit
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_db
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    DataSourceStatus,
    DataSourceType,
    JobStatus,
)
from nexus_app.ingest import batch as ingest_batch
from nexus_app.ingest import gateway as ingest_gateway
from nexus_app.ingest import scan as ingest_scan

router = APIRouter(
    prefix="/internal/v1",
    dependencies=[Depends(require_user)],
)

# Auth endpoints share the `/internal/v1` prefix but must NOT carry the
# `require_user` dependency — they exist so clients can *obtain* a token.
# FastAPI does not let a decorator-level `dependencies=[]` override the
# router-level deps, so we use a sibling router with no shared deps.
auth_router = APIRouter(prefix="/internal/v1/auth")

_prompt_svc = PromptProfileService()
_ai_gov_svc = AIGovernanceService()
# Production fail-fast load is in main.py lifespan. We additionally do a tolerant
# eager load here so test harnesses that instantiate TestClient(app) without the
# `with` context (which would trigger lifespan) still get a populated registry.
_rules_registry = get_governance_rules_registry()
try:
    if _rules_registry._config is None:
        _rules_registry.load()
except Exception:
    pass  # lifespan will surface the failure in production startup


def _get_registry() -> GovernanceRulesRegistry | None:
    return _rules_registry if _rules_registry._config is not None else None


_CONNECTION_CONFIG_SCHEMAS = {
    DataSourceType.NAS: domain_schemas.NasConnectionConfig,
    DataSourceType.CRAWLER: domain_schemas.CrawlerConnectionConfig,
    DataSourceType.DATABASE: domain_schemas.DatabaseConnectionConfig,
    DataSourceType.WEBHOOK: domain_schemas.WebhookConnectionConfig,
}


def _validate_connection_config(source_type: DataSourceType, config: dict) -> None:
    schema_cls = _CONNECTION_CONFIG_SCHEMAS.get(source_type)
    if schema_cls is None:
        return
    try:
        schema_cls.model_validate(config)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"connection_config invalid for source_type={source_type}: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Runtime / state
# ---------------------------------------------------------------------------

@router.get(
    "/runtime/state",
    response_model=schemas.ApiResponse[domain_schemas.RuntimeStateRead],
)
def runtime_state(request: Request, session: Session = Depends(get_db)):
    database = "ok"
    try:
        session.execute(text("select 1"))
    except Exception:
        database = "error"
    return response(
        domain_schemas.RuntimeStateRead(
            api="ok",
            database=database,
            workers="not_configured",
            queue="not_configured",
            recent_error=None,
        ),
        request,
    )


# ---------------------------------------------------------------------------
# Auth endpoints — JWT user session (login / refresh / logout)
#
# These three endpoints opt out of the router-level `require_user` dependency:
# they are how a client *obtains* a token in the first place. Each uses
# `dependencies=_AUTH_PUBLIC` to override.
# ---------------------------------------------------------------------------


def _auth_user_payload(
    user: models.UserAccount, settings: Settings
) -> schemas.AuthUser:
    org_name = user.org_unit.name if user.org_unit is not None else None
    return schemas.AuthUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        org_id=user.org_unit_id,
        org_name=org_name,
        env=settings.nexus_env,
    )


@auth_router.post(
    "/login",
    response_model=schemas.ApiResponse[schemas.TokenPair],
)  # public — no require_user
def auth_login(
    payload: schemas.LoginRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Verify username/password and mint a short-lived access token plus a
    long-lived rotating refresh token. The refresh token is persisted as a
    `refresh_token` row so logout/refresh can revoke it server-side."""
    trace_id = str(getattr(request.state, "trace_id", ""))

    user = session.scalars(
        select(models.UserAccount).where(models.UserAccount.username == payload.username)
    ).first()

    if user is None or not auth_service.verify_password(
        payload.password, user.password_hash
    ):
        write_audit(
            session,
            AuditEventType.USER_LOGIN_FAILED,
            target_type="user_account",
            target_id=payload.username,
            trace_id=trace_id,
            summary={"reason": "invalid_credentials"},
        )
        session.commit()
        raise HTTPException(status_code=401, detail="invalid username or password")

    if user.status.value != "active":
        write_audit(
            session,
            AuditEventType.USER_LOGIN_FAILED,
            target_type="user_account",
            target_id=user.id,
            trace_id=trace_id,
            summary={"reason": "user_disabled"},
            actor_type="user",
            actor_id=user.id,
        )
        session.commit()
        raise HTTPException(status_code=403, detail="user is disabled")

    access_token, _ = auth_service.encode_access_token(
        settings,
        user=user,
        org_name=user.org_unit.name if user.org_unit is not None else None,
    )
    jti, refresh_row = auth_service.issue_refresh_token(
        session, settings, user_id=user.id
    )
    refresh_token = auth_service.encode_refresh_token(
        settings, jti=jti, user_id=user.id
    )

    write_audit(
        session,
        AuditEventType.USER_LOGIN_SUCCEEDED,
        target_type="user_account",
        target_id=user.id,
        trace_id=trace_id,
        summary={"jti": jti, "username": user.username},
        actor_type="user",
        actor_id=user.id,
    )
    session.commit()

    return response(
        schemas.TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user=_auth_user_payload(user, settings),
        ),
        request,
    )


@auth_router.post(
    "/refresh",
    response_model=schemas.ApiResponse[schemas.TokenRefresh],
)
def auth_refresh(
    payload: schemas.RefreshRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Rotate the refresh token: verify signature, look up the jti, revoke it,
    and issue a fresh access+refresh pair. Reusing a revoked jti is logged but
    rejected — this catches replay attempts."""
    trace_id = str(getattr(request.state, "trace_id", ""))

    try:
        claims = auth_service.decode_refresh_token(settings, payload.refresh_token)
    except auth_service.InvalidTokenError as exc:
        write_audit(
            session,
            AuditEventType.TOKEN_REFRESH_FAILED,
            target_type="refresh_token",
            target_id="invalid",
            trace_id=trace_id,
            summary={"reason": "decode_failed", "detail": str(exc)[:200]},
        )
        session.commit()
        raise HTTPException(status_code=401, detail="invalid refresh token") from exc

    jti = claims.get("jti", "")
    row = auth_service.lookup_refresh_token(session, jti)
    if row is None or not auth_service.refresh_token_is_usable(row):
        write_audit(
            session,
            AuditEventType.TOKEN_REFRESH_FAILED,
            target_type="refresh_token",
            target_id=jti or "missing",
            trace_id=trace_id,
            summary={
                "reason": "revoked_or_expired_or_unknown",
                "found": row is not None,
            },
            actor_type="user",
            actor_id=claims.get("sub"),
        )
        session.commit()
        raise HTTPException(status_code=401, detail="refresh token expired or revoked")

    user = session.get(models.UserAccount, row.user_id)
    if user is None or user.status.value != "active":
        auth_service.revoke_refresh_token(row)
        session.commit()
        raise HTTPException(status_code=401, detail="user no longer active")

    auth_service.revoke_refresh_token(row)
    new_jti, new_row = auth_service.issue_refresh_token(
        session, settings, user_id=user.id, parent_jti=jti
    )
    access_token, _ = auth_service.encode_access_token(
        settings,
        user=user,
        org_name=user.org_unit.name if user.org_unit is not None else None,
    )
    refresh_token = auth_service.encode_refresh_token(
        settings, jti=new_jti, user_id=user.id
    )

    write_audit(
        session,
        AuditEventType.TOKEN_REFRESHED,
        target_type="refresh_token",
        target_id=new_jti,
        trace_id=trace_id,
        summary={"parent_jti": jti, "username": user.username},
        actor_type="user",
        actor_id=user.id,
    )
    session.commit()

    return response(
        schemas.TokenRefresh(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
        ),
        request,
    )


@auth_router.post(
    "/logout",
    response_model=schemas.ApiResponse[schemas.LogoutResult],
)
def auth_logout(
    payload: schemas.LogoutRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Best-effort revoke of the supplied refresh token. Always returns 200 —
    the console treats logout as terminal regardless. Idempotent."""
    trace_id = str(getattr(request.state, "trace_id", ""))

    try:
        claims = auth_service.decode_refresh_token(settings, payload.refresh_token)
    except auth_service.InvalidTokenError:
        return response(schemas.LogoutResult(ok=True), request)

    jti = claims.get("jti", "")
    row = auth_service.lookup_refresh_token(session, jti)
    if row is not None and row.revoked_at is None:
        auth_service.revoke_refresh_token(row)
        write_audit(
            session,
            AuditEventType.USER_LOGOUT,
            target_type="refresh_token",
            target_id=jti,
            trace_id=trace_id,
            summary={"user_id": row.user_id},
            actor_type="user",
            actor_id=row.user_id,
        )
        session.commit()

    return response(schemas.LogoutResult(ok=True), request)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@router.post(
    "/org-units",
    response_model=schemas.ApiResponse[domain_schemas.OrgUnitRead],
    status_code=201,
)
def create_org_unit(
    payload: domain_schemas.OrgUnitCreate, request: Request, session: Session = Depends(get_db)
):
    return response(services.create_org_unit(session, payload), request)


@router.get("/org-units", response_model=schemas.ListResponse[domain_schemas.OrgUnitRead])
def list_org_units(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.OrgUnit), request)


@router.get(
    "/org-units/{org_unit_id}", response_model=schemas.ApiResponse[domain_schemas.OrgUnitRead]
)
def get_org_unit(org_unit_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.OrgUnit, org_unit_id, "org_unit"), request)


@router.post("/users", response_model=schemas.ApiResponse[domain_schemas.UserRead], status_code=201)
def create_user(
    payload: domain_schemas.UserCreate, request: Request, session: Session = Depends(get_db)
):
    return response(services.create_user(session, payload), request)


@router.get("/users", response_model=schemas.ListResponse[domain_schemas.UserRead])
def list_users(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.UserAccount), request)


@router.get("/users/{user_id}", response_model=schemas.ApiResponse[domain_schemas.UserRead])
def get_user(user_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.UserAccount, user_id, "user"), request)


@router.post(
    "/api-callers",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerMintRead],
    status_code=201,
)
def create_api_caller(
    payload: domain_schemas.ApiCallerCreate, request: Request, session: Session = Depends(get_db)
):
    """Mint a new ApiCaller. If `caller_key` is omitted (recommended), the
    server generates a high-entropy key, stores only its sha256 hash, and
    returns the plaintext in `caller_key_plaintext` exactly once. The console
    must surface this to the operator and they must save it; subsequent reads
    return `caller_key_plaintext=null`."""
    result = services.mint_api_caller(
        session,
        payload,
        trace_id=str(getattr(request.state, "trace_id", "")),
    )
    read = domain_schemas.ApiCallerMintRead.model_validate(result.caller)
    if result.caller_key_plaintext is not None:
        read = read.model_copy(
            update={"caller_key_plaintext": result.caller_key_plaintext}
        )
    return response(read, request)


@router.get("/api-callers", response_model=schemas.ListResponse[domain_schemas.ApiCallerRead])
def list_api_callers(request: Request, session: Session = Depends(get_db)):
    rows = list(
        session.scalars(
            select(models.ApiCaller).order_by(models.ApiCaller.created_at.desc())
        ).all()
    )
    return list_response(rows, request)


@router.get(
    "/api-callers/{api_caller_id}",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
)
def get_api_caller(api_caller_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.ApiCaller, api_caller_id, "api_caller"), request
    )


@router.delete(
    "/api-callers/{api_caller_id}",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
)
def revoke_api_caller(
    api_caller_id: str, request: Request, session: Session = Depends(get_db)
):
    """Soft-revoke: mark `revoked_at`, leaving the row intact for audit. Future
    auth attempts fail with 403. Idempotent — re-deleting a revoked caller
    returns the existing row unchanged."""
    caller = session.get(models.ApiCaller, api_caller_id)
    if caller is None:
        raise HTTPException(
            status_code=404, detail=f"api_caller '{api_caller_id}' not found"
        )
    if caller.revoked_at is None:
        caller.revoked_at = datetime.now(timezone.utc)
        write_audit(
            session,
            AuditEventType.API_CALLER_REVOKED,
            target_type="api_caller",
            target_id=caller.id,
            trace_id=str(getattr(request.state, "trace_id", "")),
            summary={"name": caller.name},
        )
        session.commit()
        session.refresh(caller)
    return response(domain_schemas.ApiCallerRead.model_validate(caller), request)


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

@router.post(
    "/data-sources",
    response_model=schemas.ApiResponse[domain_schemas.DataSourceRead],
    status_code=201,
)
def create_data_source(
    payload: domain_schemas.DataSourceCreate, request: Request, session: Session = Depends(get_db)
):
    if payload.connection_config is not None:
        _validate_connection_config(payload.source_type, payload.connection_config)
    return response(
        services.create_data_source(
            session,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        ),
        request,
    )


@router.get("/data-sources", response_model=schemas.ListResponse[domain_schemas.DataSourceRead])
def list_data_sources(
    request: Request,
    include_deleted: bool = False,
    session: Session = Depends(get_db),
):
    """List data sources, hiding soft-deleted rows by default. Pass
    `include_deleted=true` to surface tombstones for audit views."""
    stmt = select(models.DataSource).order_by(models.DataSource.created_at.desc())
    if not include_deleted:
        stmt = stmt.where(models.DataSource.deleted_at.is_(None))
    return list_response(list(session.scalars(stmt).all()), request)


@router.get(
    "/data-sources/{data_source_id}",
    response_model=schemas.ApiResponse[domain_schemas.DataSourceRead],
)
def get_data_source(data_source_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.DataSource, data_source_id, "data_source"), request
    )


@router.delete(
    "/data-sources/{data_source_id}",
    response_model=schemas.ApiResponse[schemas.DataSourceDeleteResult],
)
def delete_data_source(
    data_source_id: str,
    request: Request,
    force: bool = False,
    session: Session = Depends(get_db),
):
    """Soft-delete a data source (`deleted_at` + status `disabled`).

    Refuses with 409 when any `raw_object` or `document_asset` still references
    the source. Pass `force=true` to soft-delete anyway (lineage preserved but
    orphaned).
    """
    source = session.get(models.DataSource, data_source_id)
    if source is None:
        raise HTTPException(
            status_code=404, detail=f"data_source '{data_source_id}' not found"
        )
    if source.deleted_at is not None:
        return response(
            schemas.DataSourceDeleteResult(
                data_source_id=source.id,
                deleted_at=source.deleted_at.isoformat(),
                status=source.status.value,
            ),
            request,
        )

    if not force:
        raw_count = session.scalar(
            select(models.RawObject.id)
            .where(models.RawObject.data_source_id == source.id)
            .limit(1)
        )
        asset_count = session.scalar(
            select(models.DocumentAsset.id)
            .where(models.DocumentAsset.data_source_id == source.id)
            .limit(1)
        )
        if raw_count is not None or asset_count is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "data_source has dependent raw_objects or assets; "
                    "pass force=true to soft-delete anyway "
                    "(downstream lineage will be preserved but orphaned)"
                ),
            )

    now = datetime.now(timezone.utc)
    source.deleted_at = now
    source.status = DataSourceStatus.DISABLED

    write_audit(
        session,
        AuditEventType.DATA_SOURCE_DELETED,
        target_type="data_source",
        target_id=source.id,
        trace_id=str(getattr(request.state, "trace_id", "")),
        summary={
            "code": source.code,
            "source_type": source.source_type.value,
            "force": force,
        },
    )
    session.commit()
    session.refresh(source)
    return response(
        schemas.DataSourceDeleteResult(
            data_source_id=source.id,
            deleted_at=source.deleted_at.isoformat(),
            status=source.status.value,
        ),
        request,
    )


@router.post(
    "/data-sources/{data_source_id}/scan-tasks",
    response_model=schemas.ApiResponse[domain_schemas.DataSourceScanTaskRead],
    status_code=202,
)
def create_data_source_scan_task(
    data_source_id: str,
    payload: domain_schemas.DataSourceScanTaskCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        result = ingest_scan.create_scan_task(
            session,
            data_source_id,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except ingest_batch.DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ingest_scan.ScanTaskUnsupportedSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ingest_scan.ScanTaskError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ingest_batch.BatchClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ingest_batch.BatchFullError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return response(
        domain_schemas.DataSourceScanTaskRead(
            batch=domain_schemas.IngestBatchRead.model_validate(result.batch),
            items=[_append_read(item) for item in result.items],
        ),
        request,
    )


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

@router.post(
    "/ingest/batches",
    response_model=schemas.ApiResponse[domain_schemas.IngestBatchRead],
    status_code=201,
)
def create_multi_raw_batch(
    payload: domain_schemas.MultiRawBatchCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    """TP-W5-01: create an empty batch in `open` state for subsequent file append."""
    try:
        batch = ingest_batch.create_batch(
            session,
            data_source_id=payload.data_source_id,
            batch_idempotency_key=payload.batch_idempotency_key,
            owner_user_id=payload.owner_user_id,
            summary=payload.summary,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except ingest_batch.DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.IngestBatchRead.model_validate(batch), request)


def _append_read(result: ingest_batch.BatchAppendResult) -> domain_schemas.IngestFileAppendRead:
    return domain_schemas.IngestFileAppendRead(
        raw_object_id=result.raw_object.id,
        job_id=result.job.id,
        job_status=result.job.status,
        file_idempotency_key=result.raw_object.file_idempotency_key or "",
        duplicate=result.duplicate,
    )


@router.post(
    "/ingest/batches/{batch_id}/files",
    response_model=schemas.ApiResponse[domain_schemas.IngestFileAppendRead],
    status_code=202,
)
def append_file_to_batch(
    batch_id: str,
    payload: domain_schemas.IngestFileAppend,
    request: Request,
    session: Session = Depends(get_db),
):
    """TP-W5-01: append a single file to an open batch.

    Idempotent on `(batch_id, file_idempotency_key)`. Returns 409 when the batch
    is no longer open, 422 when batch capacity is exceeded, 404 when the batch
    or its data source is missing.
    """
    try:
        content = base64.b64decode(payload.content_base64)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid content_base64: {exc}") from exc
    try:
        result = ingest_batch.append_file_to_batch(
            session,
            batch_id,
            file_idempotency_key=payload.file_idempotency_key,
            filename=payload.filename,
            content=content,
            mime_type=payload.content_type or "application/octet-stream",
            source_uri=payload.source_uri,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except ingest_batch.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ingest_batch.DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ingest_batch.BatchClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ingest_batch.BatchFullError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(_append_read(result), request)


@router.post(
    "/ingest/files/multi",
    response_model=schemas.ApiResponse[domain_schemas.IngestMultiFileResult],
    status_code=202,
)
def submit_ingest_multi_file(
    payload: domain_schemas.IngestMultiFileSubmit,
    request: Request,
    session: Session = Depends(get_db),
):
    """TP-W5-04: single-call convenience that creates a batch and appends all files.

    On any append error the entire transaction is rolled back (no partial batch).
    """
    MAX_FILES_PER_REQUEST = 20
    if len(payload.files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=422,
            detail=f"max {MAX_FILES_PER_REQUEST} files per multi submit (got {len(payload.files)})",
        )

    trace_id = str(getattr(request.state, "trace_id", ""))
    try:
        batch = ingest_batch.create_batch(
            session,
            data_source_id=payload.data_source_id,
            batch_idempotency_key=payload.batch_idempotency_key,
            owner_user_id=payload.owner_user_id,
            trace_id=trace_id,
        )
    except ingest_batch.DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    items: list[domain_schemas.IngestFileAppendRead] = []
    try:
        for item in payload.files:
            try:
                content = base64.b64decode(item.content_base64)
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"invalid content_base64 for {item.file_idempotency_key}: {exc}",
                ) from exc
            result = ingest_batch.append_file_to_batch(
                session,
                batch.id,
                file_idempotency_key=item.file_idempotency_key,
                filename=item.filename,
                content=content,
                mime_type=item.content_type or "application/octet-stream",
                source_uri=item.source_uri,
                trace_id=trace_id,
            )
            items.append(_append_read(result))
    except ingest_batch.BatchClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ingest_batch.BatchFullError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.refresh(batch)
    return response(
        domain_schemas.IngestMultiFileResult(
            batch=domain_schemas.IngestBatchRead.model_validate(batch),
            items=items,
        ),
        request,
    )


def _accepted_read(result: ingest_gateway.IngestAccepted) -> domain_schemas.IngestAcceptedRead:
    return domain_schemas.IngestAcceptedRead(
        batch=domain_schemas.IngestBatchRead.model_validate(result.batch),
        raw_object=domain_schemas.RawObjectRead.model_validate(result.raw_object),
        job=domain_schemas.JobRead.model_validate(result.job),
    )


@router.post(
    "/ingest/files",
    response_model=schemas.ApiResponse[domain_schemas.IngestAcceptedRead],
    status_code=202,
)
def submit_ingest_file(
    payload: domain_schemas.IngestFileSubmit, request: Request, session: Session = Depends(get_db)
):
    try:
        result = ingest_gateway.submit_file_ingest(
            session,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except ingest_gateway.IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(_accepted_read(result), request)


@router.post(
    "/ingest/files/upload",
    response_model=schemas.ApiResponse[domain_schemas.IngestAcceptedRead],
    status_code=202,
)
async def submit_ingest_file_upload(
    data_source_id: str = Form(...),
    idempotency_key: str = Form(...),
    file: UploadFile = File(...),
    source_uri: str | None = Form(None),
    owner_user_id: str | None = Form(None),
    request: Request = None,
    session: Session = Depends(get_db),
):
    """File upload endpoint using multipart/form-data (for large files or browser uploads)."""
    content = await file.read()
    try:
        result = ingest_gateway.submit_file_bytes(
            session,
            data_source_id=data_source_id,
            idempotency_key=idempotency_key,
            content=content,
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            source_uri=source_uri,
            owner_user_id=owner_user_id,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except ingest_gateway.IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(_accepted_read(result), request)


@router.post(
    "/ingest/crawler-packages",
    response_model=schemas.ApiResponse[domain_schemas.IngestAcceptedRead],
    status_code=202,
)
def submit_crawler_package(
    payload: domain_schemas.CrawlerPackageSubmit,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        result = ingest_gateway.submit_crawler_package(
            session,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except ingest_gateway.IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(_accepted_read(result), request)


@router.get("/ingest/batches", response_model=schemas.ListResponse[domain_schemas.IngestBatchRead])
def list_ingest_batches(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.IngestBatch), request)


@router.get(
    "/ingest/batches/{batch_id}",
    response_model=schemas.ApiResponse[domain_schemas.IngestBatchRead],
)
def get_ingest_batch(batch_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.IngestBatch, batch_id, "ingest_batch"), request
    )


@router.get(
    "/ingest/batches/{batch_id}/raw-objects",
    response_model=schemas.ListResponse[domain_schemas.RawObjectRead],
)
def list_raw_objects_for_batch(batch_id: str, request: Request, session: Session = Depends(get_db)):
    services.get_row(session, models.IngestBatch, batch_id, "ingest_batch")
    rows = list(
        session.scalars(
            select(models.RawObject)
            .where(models.RawObject.batch_id == batch_id)
            .order_by(models.RawObject.created_at.desc())
        ).all()
    )
    return list_response(rows, request)


@router.get("/raw-objects", response_model=schemas.ListResponse[domain_schemas.RawObjectRead])
def list_raw_objects(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.RawObject), request)


@router.get(
    "/raw-objects/{raw_object_id}",
    response_model=schemas.ApiResponse[domain_schemas.RawObjectRead],
)
def get_raw_object(raw_object_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.RawObject, raw_object_id, "raw_object"), request
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=schemas.ListResponse[domain_schemas.JobRead])
def list_jobs(request: Request, session: Session = Depends(get_db)):
    return list_response(pipeline.list_jobs(session), request)


@router.get("/jobs/{job_id}", response_model=schemas.ApiResponse[domain_schemas.JobRead])
def get_job(job_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.Job, job_id, "job"), request)


@router.get(
    "/jobs/{job_id}/stages",
    response_model=schemas.ListResponse[domain_schemas.JobStageRead],
)
def list_job_stages(job_id: str, request: Request, session: Session = Depends(get_db)):
    services.get_row(session, models.Job, job_id, "job")
    return list_response(pipeline.list_job_stages(session, job_id), request)


_JOB_RETRIABLE_STATUSES = {
    JobStatus.FAILED,
    JobStatus.DEAD_LETTERED,
    JobStatus.CANCELLED,
}

_JOB_IMMEDIATE_CANCEL_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.FAILED,
    JobStatus.DEAD_LETTERED,
}


@router.post(
    "/jobs/{job_id}/retry",
    response_model=schemas.ApiResponse[schemas.JobActionResult],
)
def retry_job(job_id: str, request: Request, session: Session = Depends(get_db)):
    """Reschedule a stalled job. Allowed only when the job is in `failed`,
    `dead_lettered`, or `cancelled` — running jobs already have automatic
    retry, succeeded jobs cannot meaningfully be re-run.
    """
    job = session.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    if job.status not in _JOB_RETRIABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"job is in status '{job.status.value}', only "
                f"{[s.value for s in _JOB_RETRIABLE_STATUSES]} are retriable"
            ),
        )

    previous_status = job.status.value
    previous_attempt_count = job.attempt_count

    job.status = JobStatus.QUEUED
    job.attempt_count = 0
    job.locked_by = None
    job.locked_at = None
    job.lock_expires_at = None
    job.heartbeat_at = None
    job.failure_reason = None
    job.cancel_requested_at = None
    job.next_run_at = datetime.now(timezone.utc)

    trace_id = str(getattr(request.state, "trace_id", ""))
    write_audit(
        session,
        AuditEventType.JOB_RETRIED,
        target_type="job",
        target_id=job.id,
        trace_id=trace_id,
        summary={
            "previous_status": previous_status,
            "previous_attempt_count": previous_attempt_count,
            "retry_count": job.retry_count,
        },
    )
    if job.raw_object_id is not None:
        version = session.scalars(
            select(models.DocumentVersion).where(
                models.DocumentVersion.raw_object_id == job.raw_object_id
            )
        ).first()
        if version is not None and version.version_status == AssetVersionStatus.FAILED:
            version.version_status = AssetVersionStatus.PROCESSING
            version.failure_reason = None
            write_audit(
                session,
                AuditEventType.VERSION_STATUS_CHANGED,
                target_type="document_version",
                target_id=version.id,
                trace_id=trace_id,
                summary={
                    "from_status": AssetVersionStatus.FAILED.value,
                    "to_status": AssetVersionStatus.PROCESSING.value,
                    "reason": "operator_retry",
                    "job_id": job.id,
                },
            )

    session.commit()
    session.refresh(job)
    return response(
        schemas.JobActionResult(
            job_id=job.id,
            status=job.status.value,
            attempt_count=job.attempt_count,
        ),
        request,
    )


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=schemas.ApiResponse[schemas.JobActionResult],
)
def cancel_job(job_id: str, request: Request, session: Session = Depends(get_db)):
    """Cancel a job.

    - `queued` / `failed` / `dead_lettered` — flipped to `cancelled` immediately.
    - `running` — sets `cancel_requested_at` so the worker can honor it at the
      next stage boundary. Status stays `running` until the worker observes
      the flag; status code 202.
    - `succeeded` / `cancelled` — 409 (terminal).
    """
    job = session.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")

    trace_id = str(getattr(request.state, "trace_id", ""))

    if job.status in _JOB_IMMEDIATE_CANCEL_STATUSES:
        previous_status = job.status.value
        job.status = JobStatus.CANCELLED
        job.cancel_requested_at = datetime.now(timezone.utc)
        job.locked_by = None
        job.lock_expires_at = None
        write_audit(
            session,
            AuditEventType.JOB_CANCELLED,
            target_type="job",
            target_id=job.id,
            trace_id=trace_id,
            summary={"previous_status": previous_status, "effective": "immediate"},
        )
        session.commit()
        session.refresh(job)
        return response(
            schemas.JobActionResult(
                job_id=job.id,
                status=job.status.value,
                cancel_requested_at=job.cancel_requested_at.isoformat(),
            ),
            request,
        )

    if job.status == JobStatus.RUNNING:
        if job.cancel_requested_at is None:
            job.cancel_requested_at = datetime.now(timezone.utc)
            write_audit(
                session,
                AuditEventType.JOB_CANCELLED,
                target_type="job",
                target_id=job.id,
                trace_id=trace_id,
                summary={
                    "previous_status": JobStatus.RUNNING.value,
                    "effective": "requested_pending_worker",
                },
            )
            session.commit()
            session.refresh(job)
        return JSONResponse(
            status_code=202,
            content=schemas.ApiResponse[schemas.JobActionResult](
                data=schemas.JobActionResult(
                    job_id=job.id,
                    status=job.status.value,
                    cancel_requested_at=job.cancel_requested_at.isoformat(),
                ),
                meta=schemas.ResponseMeta(trace_id=trace_id),
            ).model_dump(),
        )

    raise HTTPException(
        status_code=409,
        detail=f"job is in terminal status '{job.status.value}' and cannot be cancelled",
    )


# ---------------------------------------------------------------------------
# Assets, parse artifacts, normalized refs, audit logs
# ---------------------------------------------------------------------------

@router.get(
    "/parse-artifacts",
    response_model=schemas.ListResponse[domain_schemas.ParseArtifactRead],
)
def list_parse_artifacts(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.ParseArtifact), request)


@router.get(
    "/normalized-refs", response_model=schemas.ListResponse[domain_schemas.NormalizedAssetRefRead]
)
def list_normalized_refs(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.NormalizedAssetRef), request)


@router.get("/audit-logs", response_model=schemas.ListResponse[domain_schemas.AuditLogRead])
def list_audit_logs(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.AuditLog), request)


@router.get("/assets", response_model=schemas.ListResponse[domain_schemas.DocumentAssetRead])
def list_assets(request: Request, session: Session = Depends(get_db)):
    return list_response(pipeline.list_assets(session), request)


@router.get(
    "/assets/{asset_id}",
    response_model=schemas.ApiResponse[domain_schemas.AssetDetailRead],
)
def get_asset(asset_id: str, request: Request, session: Session = Depends(get_db)):
    asset = services.get_row(session, models.DocumentAsset, asset_id, "asset")
    versions = pipeline.list_asset_versions(session, asset_id)
    refs = pipeline.list_normalized_refs_for_versions(session, [version.id for version in versions])
    current_version = pipeline.get_current_version(session, asset_id)
    current_ref = (
        pipeline.get_current_normalized_ref(session, current_version.id)
        if current_version is not None
        else None
    )
    detail = domain_schemas.AssetDetailRead(
        asset=domain_schemas.DocumentAssetRead.model_validate(asset),
        versions=[
            domain_schemas.DocumentVersionRead.model_validate(version)
            for version in versions
        ],
        normalized_refs=[
            domain_schemas.NormalizedAssetRefRead.model_validate(ref) for ref in refs
        ],
        current_version=(
            domain_schemas.DocumentVersionRead.model_validate(current_version)
            if current_version is not None
            else None
        ),
        current_normalized_ref=(
            domain_schemas.NormalizedAssetRefRead.model_validate(current_ref)
            if current_ref is not None
            else None
        ),
    )
    return response(detail, request)


@router.get(
    "/assets/{asset_id}/versions",
    response_model=schemas.ListResponse[domain_schemas.DocumentVersionRead],
)
def list_asset_versions(asset_id: str, request: Request, session: Session = Depends(get_db)):
    services.get_row(session, models.DocumentAsset, asset_id, "asset")
    return list_response(pipeline.list_asset_versions(session, asset_id), request)


# ---------------------------------------------------------------------------
# AI Prompt Profile endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/ai/prompt-profiles",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
    status_code=201,
)
def create_prompt_profile(
    payload: domain_schemas.PromptProfileCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    profile = _prompt_svc.create_profile(
        session,
        profile_name=payload.profile_name,
        task_type=payload.task_type,
        litellm_model_alias=payload.litellm_model_alias,
        prompt_version=payload.prompt_version,
        prompt_template=payload.prompt_template,
        scenario=payload.scenario,
        output_schema_version=payload.output_schema_version,
        scoring_weight_version=payload.scoring_weight_version,
        temperature=payload.temperature,
        max_input_tokens=payload.max_input_tokens,
        redaction_policy=payload.redaction_policy,
    )
    session.commit()
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.get(
    "/ai/prompt-profiles",
    response_model=schemas.ListResponse[domain_schemas.PromptProfileRead],
)
def list_prompt_profiles(
    request: Request,
    profile_name: str | None = None,
    session: Session = Depends(get_db),
):
    profiles = _prompt_svc.list_profiles(session, profile_name=profile_name)
    return list_response(
        [domain_schemas.PromptProfileRead.model_validate(p) for p in profiles], request
    )


@router.get(
    "/ai/prompt-profiles/{profile_id}",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
)
def get_prompt_profile(
    profile_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        profile = _prompt_svc.get_profile(session, profile_id)
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.put(
    "/ai/prompt-profiles/{profile_name}/active",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
)
def update_prompt_profile(
    profile_name: str,
    payload: domain_schemas.PromptProfileUpdate,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        profile = _prompt_svc.update_profile(
            session, profile_name, **payload.model_dump(exclude_none=True)
        )
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.post(
    "/ai/prompt-profiles/{profile_id}/disable",
    response_model=schemas.ApiResponse[domain_schemas.PromptProfileRead],
)
def disable_prompt_profile(
    profile_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        profile = _prompt_svc.disable_profile(session, profile_id)
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return response(domain_schemas.PromptProfileRead.model_validate(profile), request)


@router.post(
    "/ai/prompt-profiles/{profile_id}/dry-run",
    response_model=schemas.ApiResponse[domain_schemas.PromptDryRunRead],
)
def dry_run_prompt_profile(
    profile_id: str,
    payload: domain_schemas.PromptDryRunCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    registry = _get_registry()
    try:
        result = _prompt_svc.dry_run(
            session,
            profile_id,
            payload.normalized_ref_id,
            input_overrides=payload.input_overrides,
            registry=registry,
        )
    except PromptProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(domain_schemas.PromptDryRunRead.model_validate(result), request)


# ---------------------------------------------------------------------------
# AI Governance Run endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/ai/governance-runs",
    response_model=schemas.ApiResponse[domain_schemas.AIGovernanceRunRead],
    status_code=201,
)
def create_governance_run(
    payload: domain_schemas.AIGovernanceRunCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    registry = _get_registry()
    try:
        run = _ai_gov_svc.run_governance(
            session,
            normalized_ref_id=payload.normalized_ref_id,
            profile_id=payload.profile_id,
            registry=registry,
        )
    except AIGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return response(domain_schemas.AIGovernanceRunRead.model_validate(run), request)


@router.get(
    "/ai/governance-runs",
    response_model=schemas.ListResponse[domain_schemas.AIGovernanceRunRead],
)
def list_governance_runs(
    request: Request,
    normalized_ref_id: str | None = None,
    profile_id: str | None = None,
    session: Session = Depends(get_db),
):
    runs = _ai_gov_svc.list_governance_runs(
        session, normalized_ref_id=normalized_ref_id, profile_id=profile_id
    )
    return list_response(
        [domain_schemas.AIGovernanceRunRead.model_validate(r) for r in runs], request
    )


@router.get(
    "/ai/governance-runs/{run_id}",
    response_model=schemas.ApiResponse[domain_schemas.AIGovernanceRunRead],
)
def get_governance_run(
    run_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        run = _ai_gov_svc.get_governance_run(session, run_id)
    except AIGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.AIGovernanceRunRead.model_validate(run), request)


@router.get(
    "/ai/governance-runs/{run_id}/quality-summary",
    response_model=schemas.ApiResponse[dict],
)
def get_governance_run_quality_summary(
    run_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        summary = _ai_gov_svc.get_quality_summary(session, run_id)
    except AIGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="No quality summary available for this run")
    return response(summary, request)


# ---------------------------------------------------------------------------
# Admin: governance rules hot-reload
# ---------------------------------------------------------------------------

@router.get("/admin/governance-rules")
def get_governance_rules(request: Request):
    try:
        raw = _rules_registry.get_raw()
        etag = _rules_registry.get_etag()
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Failed to read governance rules: {exc}") from exc
    body = schemas.ApiResponse(
        data=raw,
        meta=schemas.ResponseMeta(trace_id=str(getattr(request.state, "trace_id", ""))),
    ).model_dump()
    return JSONResponse(content=body, headers={"ETag": etag})


@router.put("/admin/governance-rules", response_model=schemas.ApiResponse[dict])
def update_governance_rules(
    payload: dict,
    request: Request,
    if_match: str | None = Header(None, alias="If-Match"),
    recompute: bool = False,
    recompute_scope: str = "review_required_only",
    session: Session = Depends(get_db),
):
    """Validate, persist (with file lock), and immediately hot-reload governance_rules.json."""
    if if_match is None:
        raise HTTPException(
            status_code=428,
            detail="If-Match header is required to prevent lost updates",
        )
    before_etag = if_match
    try:
        config = _rules_registry.save_and_reload(payload, expected_etag=if_match)
    except RulesEtagMismatchError as exc:
        current_raw = _rules_registry.get_raw()
        return JSONResponse(
            status_code=409,
            content={
                "detail": "governance_rules.json has been modified by another editor",
                "current_etag": exc.current_etag,
                "current_rules": current_raw,
            },
            headers={"ETag": exc.current_etag},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Failed to save governance rules: {exc}") from exc
    new_etag = _rules_registry.get_etag()

    trace_id = str(getattr(request.state, "trace_id", ""))
    write_audit(
        session,
        AuditEventType.GOVERNANCE_RULES_UPDATED,
        target_type="governance_rules",
        target_id="governance_rules.json",
        trace_id=trace_id,
        summary={
            "before_etag": before_etag,
            "after_etag": new_etag,
            "schema_version": config.schema_version,
            "classifications": len(config.classifications),
            "levels": len(config.levels),
            "tags": len(config.tags),
            "recompute_requested": recompute,
        },
    )

    recompute_summary: dict | None = None
    if recompute:
        if recompute_scope not in ("review_required_only", "all_affected"):
            raise HTTPException(
                status_code=422,
                detail=f"invalid recompute_scope '{recompute_scope}'; "
                "must be 'review_required_only' or 'all_affected'",
            )
        from nexus_app.governance.recompute import trigger_recompute
        recompute_summary = trigger_recompute(
            session,
            current_schema_version=config.schema_version,
            current_content_hash=new_etag.split("-", 1)[-1],
            scope=recompute_scope,  # type: ignore[arg-type]
            trace_id=trace_id,
        )

    session.commit()

    body = schemas.ApiResponse(
        data={
            "schema_version": config.schema_version,
            "classifications": len(config.classifications),
            "levels": len(config.levels),
            "tags": len(config.tags),
            "quality_dimensions": len(config.quality_scoring.dimensions),
            "recompute": recompute_summary,
        },
        meta=schemas.ResponseMeta(trace_id=trace_id),
    ).model_dump()
    return JSONResponse(content=body, headers={"ETag": new_etag})


@router.post("/admin/governance-rules/reload", response_model=schemas.ApiResponse[dict])
def reload_governance_rules(request: Request):
    try:
        config = _rules_registry.reload()
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Failed to reload governance rules: {exc}") from exc
    return response({"schema_version": config.schema_version,
                     "classifications": len(config.classifications),
                     "levels": len(config.levels),
                     "tags": len(config.tags)}, request)


@router.post(
    "/admin/governance-rules/recompute",
    response_model=schemas.ApiResponse[dict],
)
def recompute_governance_rules(
    request: Request,
    scope: str = "review_required_only",
    session: Session = Depends(get_db),
):
    """Standalone recompute trigger — rerun governance against the currently-loaded rules."""
    if scope not in ("review_required_only", "all_affected"):
        raise HTTPException(
            status_code=422,
            detail=f"invalid scope '{scope}'; must be "
            "'review_required_only' or 'all_affected'",
        )
    try:
        config = _rules_registry._ensure_loaded()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"governance rules not loaded: {exc}",
        ) from exc

    etag = _rules_registry.get_etag()
    trace_id = str(getattr(request.state, "trace_id", ""))
    from nexus_app.governance.recompute import trigger_recompute

    summary = trigger_recompute(
        session,
        current_schema_version=config.schema_version,
        current_content_hash=etag.split("-", 1)[-1],
        scope=scope,  # type: ignore[arg-type]
        trace_id=trace_id,
    )
    session.commit()
    return response(summary, request)


# ---------------------------------------------------------------------------
# Governance Results endpoints
# ---------------------------------------------------------------------------

_VALID_TRAIL_VIEWS = {"full", "operator", "public"}


def _validate_view(view: str) -> str:
    if view not in _VALID_TRAIL_VIEWS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid view '{view}'; must be one of "
            f"{sorted(_VALID_TRAIL_VIEWS)}",
        )
    return view


def _serialize_result_with_view(
    result: models.GovernanceResult, view: str
) -> dict:
    """Run the result through GovernanceResultRead, then apply the redaction."""
    from nexus_app.governance.redaction import redact_governance_result

    serialized = domain_schemas.GovernanceResultRead.model_validate(result).model_dump()
    return redact_governance_result(serialized, view)  # type: ignore[arg-type]


@router.get(
    "/governance-results/{result_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_governance_result(
    result_id: str,
    request: Request,
    view: str = "full",
    session: Session = Depends(get_db),
):
    """Fetch a governance result.

    `view=full` (default) — admin / business_expert: full decision_trail.
    `view=operator` — ops dashboards: AI suggestions and confidence redacted.
    `view=public` — same redaction as the external `/open/v1` variant."""
    _validate_view(view)
    result = session.get(models.GovernanceResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"GovernanceResult '{result_id}' not found")
    return response(_serialize_result_with_view(result, view), request)


@router.get(
    "/normalized-refs/{ref_id}/governance-result",
    response_model=schemas.ApiResponse[dict],
)
def get_governance_result_for_ref(
    ref_id: str,
    request: Request,
    view: str = "full",
    session: Session = Depends(get_db),
):
    """Fetch the latest governance result for a normalized_asset_ref."""
    _validate_view(view)
    result = session.scalars(
        select(models.GovernanceResult)
        .where(models.GovernanceResult.normalized_ref_id == ref_id)
        .order_by(models.GovernanceResult.created_at.desc())
        .limit(1)
    ).first()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No governance result found for normalized_ref '{ref_id}'",
        )
    return response(_serialize_result_with_view(result, view), request)


# ---------------------------------------------------------------------------
# Manual stage restart — for human intervention when AI governance fails
# ---------------------------------------------------------------------------

@router.post(
    "/asset-versions/{version_id}/restart-governance",
    response_model=schemas.ApiResponse[dict],
)
def restart_governance_for_version(
    version_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Restart a version stuck in `failed` after AI governance exhausted retries."""
    from nexus_app.audit import write_audit as _write_audit
    from nexus_app.enums import AssetVersionStatus, AuditEventType, StageStatus

    version = session.get(models.DocumentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"version '{version_id}' not found")
    if version.version_status != AssetVersionStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"version is in status '{version.version_status.value}', "
            "only 'failed' versions can be restarted",
        )

    latest_governance_stage = session.scalars(
        select(models.JobStage)
        .join(models.Job, models.Job.id == models.JobStage.job_id)
        .where(
            models.Job.raw_object_id == version.raw_object_id,
            models.JobStage.stage_name == "governance_decision",
            models.JobStage.status == StageStatus.FAILED,
        )
        .order_by(models.JobStage.created_at.desc())
        .limit(1)
    ).first()
    if latest_governance_stage is None or not (
        latest_governance_stage.detail or {}
    ).get("restartable"):
        raise HTTPException(
            status_code=409,
            detail="version is not restartable — no governance_decision stage "
            "with detail.restartable=true found (only AI governance failures "
            "are restartable; other failures require re-ingest)",
        )

    previous_reason = version.failure_reason
    version.version_status = AssetVersionStatus.PROCESSING
    version.failure_reason = None

    trace_id = str(getattr(request.state, "trace_id", ""))
    _write_audit(
        session,
        AuditEventType.VERSION_STATUS_CHANGED,
        target_type="document_version",
        target_id=version.id,
        trace_id=trace_id,
        summary={
            "from_status": AssetVersionStatus.FAILED.value,
            "to_status": AssetVersionStatus.PROCESSING.value,
            "reason": "manual_restart",
            "previous_failure_reason": previous_reason,
            "restarted_stage": "governance_decision",
        },
    )
    session.commit()
    return response(
        {
            "version_id": version.id,
            "new_status": AssetVersionStatus.PROCESSING.value,
            "previous_failure_reason": previous_reason,
        },
        request,
    )
