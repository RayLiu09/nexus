"""System-status endpoints under `/internal/v1/`."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import response
from nexus_app import schemas as domain_schemas
from nexus_app.database import get_db

router = APIRouter()


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
