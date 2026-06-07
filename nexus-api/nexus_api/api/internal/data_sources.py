"""Data source CRUD + scan-task trigger."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal._helpers import append_read, validate_connection_config
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas, services
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType, DataSourceStatus
from nexus_app.ingest import batch as ingest_batch
from nexus_app.ingest import scan as ingest_scan

router = APIRouter()


@router.post(
    "/data-sources",
    response_model=schemas.ApiResponse[domain_schemas.DataSourceRead],
    status_code=201,
)
def create_data_source(
    payload: domain_schemas.DataSourceCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    if payload.connection_config is not None:
        validate_connection_config(payload.source_type, payload.connection_config)
    return response(
        services.create_data_source(
            session,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        ),
        request,
    )


@router.get(
    "/data-sources",
    response_model=schemas.ListResponse[domain_schemas.DataSourceRead],
)
def list_data_sources(
    request: Request,
    include_deleted: bool = False,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """List data sources, hiding soft-deleted rows by default. Pass
    `include_deleted=true` to surface tombstones for audit views."""
    base = select(models.DataSource)
    if not include_deleted:
        base = base.where(models.DataSource.deleted_at.is_(None))

    rows = list(
        session.scalars(
            base.order_by(models.DataSource.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    from sqlalchemy import func as _func
    total = int(
        session.scalar(
            select(_func.count()).select_from(base.subquery())
        )
        or 0
    )
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get(
    "/data-sources/{data_source_id}",
    response_model=schemas.ApiResponse[domain_schemas.DataSourceRead],
)
def get_data_source(data_source_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.DataSource, data_source_id, "data_source"),
        request,
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

    Refuses with 409 when any `raw_object` or `asset` still references
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
            items=[append_read(item) for item in result.items],
        ),
        request,
    )
