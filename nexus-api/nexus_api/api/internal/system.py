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
    app = getattr(request, "app", None)
    app_state = getattr(app, "state", None)
    workers = "not_configured" if app_state is None else "unknown"
    pool = getattr(app_state, "worker_pool", None)
    if pool is not None:
        state = pool.state()
        workers = f"running {state.running_threads}/{state.configured_size}" if state.enabled else "disabled"

    queue = "not_configured" if app_state is None else "unknown"
    try:
        queued = session.scalar(
            text("select count(*) from job where status = 'queued'")
        )
        queue = f"queued={queued or 0}"
    except Exception:
        queue = "error"

    return response(
        domain_schemas.RuntimeStateRead(
            api="ok",
            database=database,
            workers=workers,
            queue=queue,
            recent_error=None,
        ),
        request,
    )
