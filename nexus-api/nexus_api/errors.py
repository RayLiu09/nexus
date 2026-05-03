from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from nexus_api.schemas import ErrorPayload, ErrorResponse, ResponseMeta
from nexus_api.trace import get_trace_id


def _trace_id(request: Request) -> str:
    return str(getattr(request.state, "trace_id", None) or get_trace_id() or "")


def error_response(
    request: Request, *, status_code: int, code: str, message: str, details: list[object] | None = None
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorPayload(code=code, message=message, details=details or []),
        meta=ResponseMeta(trace_id=_trace_id(request)),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = "HTTP_ERROR"
    if exc.status_code == 404:
        code = "NOT_FOUND"
    elif exc.status_code == 409:
        code = "CONFLICT"
    elif exc.status_code == 400:
        code = "BAD_REQUEST"
    return error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail),
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
