import base64

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.auth import require_api_caller
from nexus_api.permissions import apply_permission_filter
from nexus_api.responses import list_response, response
from nexus_app import models, pipeline, schemas as domain_schemas, services
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
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_db
from nexus_app.enums import DataSourceType
from nexus_app.ingest import batch as ingest_batch
from nexus_app.ingest import gateway as ingest_gateway
from nexus_app.ingest import scan as ingest_scan

router = APIRouter(prefix="/v1")

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


@router.get("/health", response_model=schemas.ApiResponse[schemas.HealthRead])
def health(request: Request, settings: Settings = Depends(get_settings)):
    return response(
        schemas.HealthRead(
            status="ok",
            service=settings.app_name,
            environment=settings.nexus_env,
        ),
        request,
    )


@router.get("/runtime/state", response_model=schemas.ApiResponse[domain_schemas.RuntimeStateRead])
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


@router.post(
    "/org-units", response_model=schemas.ApiResponse[domain_schemas.OrgUnitRead], status_code=201
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
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
    status_code=201,
)
def create_api_caller(
    payload: domain_schemas.ApiCallerCreate, request: Request, session: Session = Depends(get_db)
):
    return response(services.create_api_caller(session, payload), request)


@router.get("/api-callers", response_model=schemas.ListResponse[domain_schemas.ApiCallerRead])
def list_api_callers(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.ApiCaller), request)


@router.get(
    "/api-callers/{api_caller_id}",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
)
def get_api_caller(api_caller_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.ApiCaller, api_caller_id, "api_caller"), request
    )


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
def list_data_sources(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.DataSource), request)


@router.get(
    "/data-sources/{data_source_id}",
    response_model=schemas.ApiResponse[domain_schemas.DataSourceRead],
)
def get_data_source(data_source_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.DataSource, data_source_id, "data_source"), request
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

    # refresh the batch so status_detail reflects all appended jobs
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
    """Validate, persist (with file lock), and immediately hot-reload governance_rules.json.

    Optional query params (Review §5.4):
    - `recompute=true` — after a successful save, reschedule affected versions for
      re-governance. The console exposes this as a checkbox so business experts
      can opt in.
    - `recompute_scope=review_required_only|all_affected` — default
      `review_required_only` only flips REVIEW_REQUIRED versions back to
      processing. AVAILABLE versions are listed in the audit log but not
      auto-rerun (publish/index disruption requires per-asset approval).
    """
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

    from nexus_app.audit import write_audit
    from nexus_app.enums import AuditEventType
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
    """Standalone recompute trigger (Review §5.4) — for the case where the
    operator wants to rerun governance against the currently-loaded rules
    without re-uploading the JSON.

    `scope=review_required_only` (default) flips REVIEW_REQUIRED versions back
    to processing. `scope=all_affected` does the same plus logs the AVAILABLE
    versions in the audit summary (still no auto re-publish).
    """
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
    `view=public` — external api_callers: decision_trail returned as []."""
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
    """Fetch the latest governance result for a normalized_asset_ref.

    See `view` semantics on /v1/governance-results/{id}."""
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
    """Restart a version stuck in `failed` after AI governance exhausted retries.

    Eligibility is determined by the latest `governance_decision` JobStage carrying
    `detail.restartable == True` (set by `run_governance_decision` when AI returned
    no output). Other failure paths (parse/normalize crashes) are not restartable
    here — they require re-ingest.

    The version is flipped back to `processing` and audited; the worker picks up
    the existing job on its next poll.
    """
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


# ---------------------------------------------------------------------------
# Search & QA endpoints (RAGFlow-backed)
# ---------------------------------------------------------------------------

def _enrich_with_nexus_refs(
    session: Session, hits: list[dict]
) -> list[dict]:
    """Enrich RAGFlow hits with NEXUS-side citation fields (normalized_ref_id,
    version_id, asset_id, nexus_chunk_id) by looking up KnowledgeChunk via
    `ragflow_chunk_id`. Items that already carry these fields (e.g. fake adapter
    output) are left untouched. Best-effort; missing chunks leave fields null.
    """
    if not hits:
        return hits

    pending: dict[str, list[dict]] = {}
    for hit in hits:
        if hit.get("nexus_chunk_id") or hit.get("normalized_ref_id"):
            continue
        ragflow_chunk_id = hit.get("chunk_id")
        if ragflow_chunk_id:
            pending.setdefault(ragflow_chunk_id, []).append(hit)

    if not pending:
        return hits

    chunks = session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.ragflow_chunk_id.in_(pending.keys()))
    ).all()
    chunk_map = {c.ragflow_chunk_id: c for c in chunks if c.ragflow_chunk_id}

    ref_ids = {c.normalized_ref_id for c in chunk_map.values()}
    refs: dict[str, models.NormalizedAssetRef] = {}
    if ref_ids:
        for ref in session.scalars(
            select(models.NormalizedAssetRef).where(
                models.NormalizedAssetRef.id.in_(ref_ids)
            )
        ).all():
            refs[ref.id] = ref

    version_ids = {r.version_id for r in refs.values()}
    versions: dict[str, models.DocumentVersion] = {}
    if version_ids:
        for ver in session.scalars(
            select(models.DocumentVersion).where(
                models.DocumentVersion.id.in_(version_ids)
            )
        ).all():
            versions[ver.id] = ver

    for ragflow_chunk_id, items in pending.items():
        chunk = chunk_map.get(ragflow_chunk_id)
        if chunk is None:
            continue
        ref = refs.get(chunk.normalized_ref_id)
        ver = versions.get(ref.version_id) if ref is not None else None
        for item in items:
            item["nexus_chunk_id"] = chunk.id
            item["normalized_ref_id"] = chunk.normalized_ref_id
            if ver is not None:
                item["version_id"] = ver.id
                item["asset_id"] = ver.asset_id

    return hits


def _hit_ref_ids(hits: list[dict]) -> list[str]:
    return [h["normalized_ref_id"] for h in hits if h.get("normalized_ref_id")]


@router.get("/search")
def search_knowledge(
    q: str,
    request: Request,
    kb: str | None = None,
    top_k: int = 10,
    similarity_threshold: float = 0.7,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Search indexed knowledge base via RAGFlow.

    Args:
        q: Search query
        kb: Knowledge type code (e.g. 'textbook_kb'). If omitted, searches default KB.
        top_k: Max results
        similarity_threshold: Minimum similarity score
    """
    import hashlib as _hashlib

    from nexus_app.audit import write_audit as _write_audit
    from nexus_app.enums import AuditEventType as _AuditEventType
    from nexus_app.index.kb_registry import get_kb_registry
    from nexus_app.index.ragflow_adapter import get_ragflow_adapter

    adapter = get_ragflow_adapter()
    registry = get_kb_registry()

    kb_code = kb or "textbook_kb"
    kb_id = registry.ensure_kb(kb_code)

    results = adapter.search(
        kb_id=kb_id,
        query=q,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )
    results = _enrich_with_nexus_refs(session, results)
    results = apply_permission_filter(caller, results)

    trace_id = request.headers.get("x-trace-id")
    query_hash = _hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
    _write_audit(
        session,
        _AuditEventType.SEARCH_QUERY_EXECUTED,
        target_type="search",
        target_id=trace_id or query_hash,
        trace_id=trace_id,
        summary={
            "query_hash": query_hash,
            "kb": kb_code,
            "hit_count": len(results),
            "hit_normalized_ref_ids": _hit_ref_ids(results),
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
        },
        actor_type="api_caller",
        actor_id=caller.id,
    )
    session.commit()

    return response(
        {
            "query": q,
            "kb": kb_code,
            "results": results,
            "count": len(results),
            "caller_id": caller.id,
        },
        request,
    )


@router.get("/qa")
def qa_knowledge(
    q: str,
    request: Request,
    kb: str | None = None,
    top_k: int = 5,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Question answering with source citations via RAGFlow.

    Args:
        q: Question
        kb: Knowledge type code. If omitted, uses default KB.
        top_k: Max source chunks to retrieve
    """
    import hashlib as _hashlib

    from nexus_app.audit import write_audit as _write_audit
    from nexus_app.enums import AuditEventType as _AuditEventType
    from nexus_app.index.kb_registry import get_kb_registry
    from nexus_app.index.ragflow_adapter import get_ragflow_adapter

    adapter = get_ragflow_adapter()
    registry = get_kb_registry()

    kb_code = kb or "textbook_kb"
    kb_id = registry.ensure_kb(kb_code)

    result = adapter.qa(kb_id=kb_id, question=q, top_k=top_k)
    sources = result.get("sources", []) or []
    sources = _enrich_with_nexus_refs(session, sources)
    sources = apply_permission_filter(caller, sources)
    result["sources"] = sources

    trace_id = request.headers.get("x-trace-id")
    question_hash = _hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
    _write_audit(
        session,
        _AuditEventType.QA_ANSWER_GENERATED,
        target_type="qa",
        target_id=trace_id or question_hash,
        trace_id=trace_id,
        summary={
            "question_hash": question_hash,
            "kb": kb_code,
            "answer_length": len(result.get("answer", "") or ""),
            "source_count": len(sources),
            "cited_normalized_ref_ids": _hit_ref_ids(sources),
            "top_k": top_k,
        },
        actor_type="api_caller",
        actor_id=caller.id,
    )
    session.commit()

    return response({"question": q, "kb": kb_code, "caller_id": caller.id, **result}, request)
