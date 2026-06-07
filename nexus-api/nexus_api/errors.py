import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from nexus_api.schemas import ErrorPayload, ErrorResponse, ResponseMeta
from nexus_api.trace import get_trace_id
from nexus_app.services import ResourceNotFoundError

logger = logging.getLogger(__name__)


def _trace_id(request: Request) -> str:
    return str(getattr(request.state, "trace_id", None) or get_trace_id() or "")


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[object] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorPayload(code=code, message=message, details=details or []),
        meta=ResponseMeta(trace_id=_trace_id(request)),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )


_HTTP_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    409: "CONFLICT",
    428: "PRECONDITION_REQUIRED",
    429: "TOO_MANY_REQUESTS",
}


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    # Preserve response headers the handler set (e.g. Retry-After on 429,
    # WWW-Authenticate on 401, ETag on optimistic-lock conflicts). FastAPI's
    # default raises HTTPException with `headers=...`; we must forward them
    # or downstream clients lose the signal.
    return error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=exc.errors(),
    )


async def integrity_exception_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return error_response(
        request,
        status_code=409,
        code="CONFLICT",
        message="Resource violates a uniqueness or foreign-key constraint",
        details=[{"reason": str(exc.orig)}],
    )


async def resource_not_found_handler(
    request: Request, exc: ResourceNotFoundError
) -> JSONResponse:
    """Map the service-layer not-found exception to the envelope 404 shape so
    handlers don't have to wrap each `services.get_row` call individually."""
    return error_response(
        request,
        status_code=404,
        code="NOT_FOUND",
        message=str(exc) or "Resource not found",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for service-layer exceptions that don't have a dedicated handler.

    Without this, FastAPI's default returns a bare `{"detail": "Internal Server
    Error"}` — non-conforming to the project's ApiResponse envelope and missing
    `trace_id`. Here we log the full exception (so operators can diagnose) and
    return a stable INTERNAL_ERROR envelope with the trace_id, never leaking
    exception detail to the response body.
    """
    trace_id = _trace_id(request)
    logger.exception(
        "unhandled exception (trace_id=%s, path=%s): %s",
        trace_id, request.url.path, exc,
    )
    return error_response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="Internal server error. Use the trace_id below to correlate logs.",
    )
