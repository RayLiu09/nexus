from typing import Any

from fastapi import Request

from nexus_api.schemas import ApiResponse, ListResponse, ResponseMeta


def trace_id_from_request(request: Request) -> str:
    trace_id = getattr(request.state, "trace_id", None)
    return str(trace_id)


def response(data: Any, request: Request) -> ApiResponse[Any]:
    return ApiResponse(data=data, meta=ResponseMeta(trace_id=trace_id_from_request(request)))


def list_response(
    data: list[Any],
    request: Request,
    *,
    page: int = 1,
    page_size: int = 100,
    total: int | None = None,
) -> ListResponse[Any]:
    """Standard list envelope.

    `total` is the size of the underlying result set (i.e. SELECT COUNT(*)),
    not the size of `data`. Pass it explicitly whenever pagination is applied
    so clients can render correct page counts. When `None` we fall back to
    `len(data)` for non-paginated callers (a no-op when the full set is
    returned).
    """
    return ListResponse(
        data=data,
        meta=ResponseMeta(
            trace_id=trace_id_from_request(request),
            page=page,
            page_size=page_size,
            total=len(data) if total is None else total,
        ),
    )
