from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas, services
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_db

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
    return response(services.get_row(session, models.ApiCaller, api_caller_id, "api_caller"), request)


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


@router.get("/ingest/batches", response_model=schemas.ListResponse[domain_schemas.IngestBatchRead])
def list_ingest_batches(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.IngestBatch), request)


@router.get(
    "/ingest/batches/{batch_id}",
    response_model=schemas.ApiResponse[domain_schemas.IngestBatchRead],
)
def get_ingest_batch(batch_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.IngestBatch, batch_id, "ingest_batch"), request)


@router.post(
    "/raw-objects", response_model=schemas.ApiResponse[domain_schemas.RawObjectRead], status_code=201
)
def create_raw_object(
    payload: domain_schemas.RawObjectCreate, request: Request, session: Session = Depends(get_db)
):
    return response(services.create_raw_object(session, payload), request)


@router.get("/raw-objects", response_model=schemas.ListResponse[domain_schemas.RawObjectRead])
def list_raw_objects(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.RawObject), request)


@router.get(
    "/raw-objects/{raw_object_id}",
    response_model=schemas.ApiResponse[domain_schemas.RawObjectRead],
)
def get_raw_object(raw_object_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.RawObject, raw_object_id, "raw_object"), request)
