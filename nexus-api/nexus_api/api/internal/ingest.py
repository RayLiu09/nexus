"""Ingest endpoints (`/internal/v1/ingest/*`, `/raw-objects/*`).

All mutating endpoints require `Idempotency-Key`; service-layer dedupe via
`ingest/gateway.py` keeps actual side effects single-writer."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal._helpers import accepted_read, append_read
from nexus_api.dependencies import require_idempotency_key
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas, services
from nexus_app.database import get_db
from nexus_app.ingest import batch as ingest_batch
from nexus_app.ingest import gateway as ingest_gateway

router = APIRouter()


@router.post(
    "/ingest/batches",
    response_model=schemas.ApiResponse[domain_schemas.IngestBatchRead],
    status_code=201,
    dependencies=[Depends(require_idempotency_key)],
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


@router.post(
    "/ingest/batches/{batch_id}/files",
    response_model=schemas.ApiResponse[domain_schemas.IngestFileAppendRead],
    status_code=202,
    dependencies=[Depends(require_idempotency_key)],
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
    return response(append_read(result), request)


@router.post(
    "/ingest/files/multi",
    response_model=schemas.ApiResponse[domain_schemas.IngestMultiFileResult],
    status_code=202,
    dependencies=[Depends(require_idempotency_key)],
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
            items.append(append_read(result))
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


@router.post(
    "/ingest/files",
    response_model=schemas.ApiResponse[domain_schemas.IngestAcceptedRead],
    status_code=202,
    dependencies=[Depends(require_idempotency_key)],
)
def submit_ingest_file(
    payload: domain_schemas.IngestFileSubmit,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        result = ingest_gateway.submit_file_ingest(
            session,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except ingest_gateway.IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(accepted_read(result), request)


@router.post(
    "/ingest/files/upload",
    response_model=schemas.ApiResponse[domain_schemas.IngestAcceptedRead],
    status_code=202,
    dependencies=[Depends(require_idempotency_key)],
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
    return response(accepted_read(result), request)


@router.post(
    "/ingest/crawler-packages",
    response_model=schemas.ApiResponse[domain_schemas.IngestAcceptedRead],
    status_code=202,
    dependencies=[Depends(require_idempotency_key)],
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
    return response(accepted_read(result), request)


@router.get(
    "/ingest/batches",
    response_model=schemas.ListResponse[domain_schemas.IngestBatchRead],
)
def list_ingest_batches(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.IngestBatch), request)


@router.get(
    "/ingest/batches/{batch_id}",
    response_model=schemas.ApiResponse[domain_schemas.IngestBatchRead],
)
def get_ingest_batch(batch_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.IngestBatch, batch_id, "ingest_batch"),
        request,
    )


@router.get(
    "/ingest/batches/{batch_id}/raw-objects",
    response_model=schemas.ListResponse[domain_schemas.RawObjectRead],
)
def list_raw_objects_for_batch(
    batch_id: str, request: Request, session: Session = Depends(get_db)
):
    services.get_row(session, models.IngestBatch, batch_id, "ingest_batch")
    rows = list(
        session.scalars(
            select(models.RawObject)
            .where(models.RawObject.batch_id == batch_id)
            .order_by(models.RawObject.created_at.desc())
        ).all()
    )
    return list_response(rows, request)


@router.get(
    "/raw-objects",
    response_model=schemas.ListResponse[domain_schemas.RawObjectRead],
)
def list_raw_objects(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.RawObject), request)


@router.get(
    "/raw-objects/{raw_object_id}",
    response_model=schemas.ApiResponse[domain_schemas.RawObjectRead],
)
def get_raw_object(raw_object_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.RawObject, raw_object_id, "raw_object"),
        request,
    )
