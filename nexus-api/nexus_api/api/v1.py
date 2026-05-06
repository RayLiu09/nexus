from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import list_response, response
from nexus_app import models, pipeline, schemas as domain_schemas, services
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_db
from nexus_app.ingest import gateway as ingest_gateway

router = APIRouter(prefix="/v1")


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
    return response(services.create_data_source(session, payload), request)


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
