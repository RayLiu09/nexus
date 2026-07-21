"""B7 (§10 阶段 B + §3.3) — POST /internal/v1/query.

Console-facing entry point for the v2 query router. Accepts a natural-
language query, runs the three-layer orchestration
(``QueryRouterV2.run()``), and returns the Composer's final Markdown
plus the v2 audit summary.

Design red lines:

* **Auth**: uses ``require_user`` (JWT session) — this endpoint is
  console-only. The paired ``POST /open/v1/query`` (B6) lives in
  ``open.py`` under ``require_api_caller``.
* **Audit**: writes ``SearchQueryExecuted`` with a
  ``RetrievalV2SummaryFields`` summary (§8.2). ``route`` is fixed to
  ``internal_query`` and ``caller_type`` to ``console_session``; the
  rest comes from ``RouterResult.audit_summary``.
* **P0 no streaming**: response is a single JSON envelope carrying
  the finished markdown. SSE / chunked streaming is deferred to
  Batch B3b (frontend delivery). §7.3 chart replacement contract is
  still respected — the router already does the swap before returning.
* **No exposed tool selection**: the payload is intentionally query-
  only; the LLM chooses which tools to call. Callers CANNOT force a
  specific tool from outside (§4.2 dispatcher contract).
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import require_user
from nexus_api.responses import response
from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType
from nexus_app.retrieval.router_v2 import QueryRouterV2, RouterResult

from nexus_api.query_router_v2_deps import get_query_router_v2
from nexus_api.query_router_v2_sse import SSE_MEDIA_TYPE, serialise_router_stream

logger = logging.getLogger(__name__)

router = APIRouter()


class QueryRouterV2Request(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)


class QueryRouterV2ResponseData(BaseModel):
    markdown: str
    intent: str
    intent_confidence: float
    invoked_tools: list[str]
    fallback_reason: str | None
    warnings: list[str]
    audit_summary: dict
    external_web_results: list[dict]


@router.post(
    "/query",
    response_model=schemas.ApiResponse[QueryRouterV2ResponseData],
)
def run_query_router_v2(
    payload: QueryRouterV2Request,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_user),
    query_router: QueryRouterV2 = Depends(get_query_router_v2),
):
    """POST /internal/v1/query — console session entry to Query Router v2."""
    result: RouterResult = query_router.run(
        session,
        query=payload.query,
        route="internal_query",
        caller_type="console_session",
    )

    trace_id = request.headers.get("x-trace-id")
    query_hash = hashlib.sha256(
        payload.query.encode("utf-8"),
    ).hexdigest()[:16]

    summary = dict(result.audit_summary)
    summary.setdefault("query_hash", query_hash)
    write_audit(
        session,
        AuditEventType.SEARCH_QUERY_EXECUTED,
        target_type="query_router_v2",
        target_id=trace_id or query_hash,
        trace_id=trace_id,
        summary=summary,
        actor_type="user_account",
        actor_id=user.id,
    )
    session.commit()

    return response(
        QueryRouterV2ResponseData(
            markdown=result.markdown,
            intent=result.intent,
            intent_confidence=result.intent_confidence,
            invoked_tools=result.invoked_tools,
            fallback_reason=result.fallback_reason,
            warnings=list(result.warnings),
            audit_summary=summary,
            external_web_results=list(getattr(result, "external_web_results", ())),
        ),
        request,
    )


# ---------------------------------------------------------------------------
# SSE variant — /internal/v1/query/stream
# ---------------------------------------------------------------------------
# Same auth + audit contract as the non-streaming variant; the response
# type is `text/event-stream` instead of an ApiResponse envelope. Frame
# schema is documented in `query_router_v2_sse.py`.


@router.post("/query/stream")
def run_query_router_v2_stream(
    payload: QueryRouterV2Request,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_user),
    query_router: QueryRouterV2 = Depends(get_query_router_v2),
) -> StreamingResponse:
    """POST /internal/v1/query/stream — SSE variant of /query."""
    trace_id = request.headers.get("x-trace-id")
    stream = serialise_router_stream(
        router=query_router,
        session=session,
        query=payload.query,
        route="internal_query",
        caller_type="console_session",
        trace_id=trace_id,
        actor_type="user_account",
        actor_id=user.id,
    )
    # `X-Accel-Buffering: no` disables nginx / cloudfront proxy
    # buffering so chunks reach the browser as they're emitted.
    return StreamingResponse(
        stream,
        media_type=SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
