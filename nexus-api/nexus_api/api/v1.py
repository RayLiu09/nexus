from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import list_response, response
from nexus_app import models, pipeline, schemas as domain_schemas, services
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.ai_governance.services import (
    AIGovernanceError,
    AIGovernanceService,
    PromptProfileNotFoundError,
    PromptProfileService,
)
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_db
from nexus_app.enums import DataSourceType
from nexus_app.ingest import gateway as ingest_gateway

router = APIRouter(prefix="/v1")

_prompt_svc = PromptProfileService()
_ai_gov_svc = AIGovernanceService()
_rules_registry = GovernanceRulesRegistry()

try:
    _rules_registry.load()
except Exception:
    pass  # registry loads lazily if config file not present during import


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
    "/ingest/batches",
    response_model=schemas.ApiResponse[domain_schemas.IngestBatchRead],
    status_code=201,
)
def create_ingest_batch(
    payload: domain_schemas.IngestBatchCreate, request: Request, session: Session = Depends(get_db)
):
    return response(services.create_ingest_batch(session, payload), request)


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

@router.get("/admin/governance-rules", response_model=schemas.ApiResponse[dict])
def get_governance_rules(request: Request):
    try:
        raw = _rules_registry.get_raw()
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Failed to read governance rules: {exc}") from exc
    return response(raw, request)


@router.put("/admin/governance-rules", response_model=schemas.ApiResponse[dict])
def update_governance_rules(payload: dict, request: Request):
    """Validate, persist, and immediately hot-reload governance_rules.json."""
    try:
        config = _rules_registry.save_and_reload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Failed to save governance rules: {exc}") from exc
    return response({"schema_version": config.schema_version,
                     "classifications": len(config.classifications),
                     "levels": len(config.levels),
                     "tags": len(config.tags),
                     "quality_dimensions": len(config.quality_scoring.dimensions)}, request)


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
