"""Request-scoped public-web search endpoints for API callers.

Firecrawl discovery and the configured Web Search provider deliberately expose
separate contracts: the former returns discovery metadata while the latter
returns provider content.  Neither path creates NEXUS assets or knowledge.
"""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import require_api_caller
from nexus_api.responses import response
from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.crawler.firecrawl_client import (
    FirecrawlClientError,
    FirecrawlDocumentClient,
    create_default_firecrawl_document_client,
)
from nexus_app.crawler.websearch_custom_client import (
    HttpWebSearchCustomClient,
    WebSearchCustomError,
)
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType
from nexus_app.retrieval.web_search import _has_sensitive_outbound_content


router = APIRouter(
    prefix="/open/v1/external-search",
    dependencies=[Depends(require_api_caller)],
)


class _ExternalSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1024)

    @field_validator("query")
    @classmethod
    def reject_sensitive_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query must not be blank")
        if _has_sensitive_outbound_content(query):
            raise ValueError("query contains sensitive content and cannot be sent externally")
        return query


class FirecrawlExternalSearchRequest(_ExternalSearchRequest):
    limit: int = Field(default=10, ge=1, le=20)
    include_domains: list[str] | None = Field(default=None, max_length=20)
    country: str = Field(default="CN", min_length=2, max_length=8)
    languages: list[str] = Field(default_factory=lambda: ["zh-CN"], min_length=1, max_length=10)


class WebSearchExternalSearchRequest(_ExternalSearchRequest):
    count: int = Field(default=10, ge=1, le=50)
    time_range: str = Field(default="OneYear", min_length=1, max_length=64)


def get_firecrawl_document_client() -> FirecrawlDocumentClient:
    return create_default_firecrawl_document_client()


def get_web_search_custom_client() -> HttpWebSearchCustomClient:
    return HttpWebSearchCustomClient()


def _provider_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="external_search_unavailable")


def _assert_caller_still_active(session: Session, caller: models.ApiCaller) -> None:
    fresh = session.get(models.ApiCaller, caller.id)
    if fresh is None or fresh.revoked_at is not None:
        raise HTTPException(status_code=403, detail="API key revoked")


def _write_external_search_audit(
    session: Session,
    *,
    caller: models.ApiCaller,
    query: str,
    provider: str,
    result_count: int,
    request: Request,
    provider_meta: dict[str, Any] | None = None,
) -> None:
    trace_id = getattr(request.state, "trace_id", None)
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    summary = {
        "route": f"external_search_{provider}",
        "provider": provider,
        "query_hash": query_hash,
        "result_count": result_count,
        "external_result_ephemeral": True,
    }
    if provider_meta:
        summary["provider_meta"] = provider_meta
    write_audit(
        session,
        AuditEventType.SEARCH_QUERY_EXECUTED,
        target_type="external_search",
        target_id=str(trace_id or query_hash),
        trace_id=str(trace_id) if trace_id else None,
        summary=summary,
        actor_type="api_caller",
        actor_id=caller.id,
    )
    session.commit()


@router.post("/firecrawl", response_model=schemas.ApiResponse[dict[str, Any]])
def search_firecrawl(
    payload: FirecrawlExternalSearchRequest,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
    client: FirecrawlDocumentClient = Depends(get_firecrawl_document_client),
):
    """Discover public URLs through Firecrawl without scraping or ingesting them."""
    try:
        results = client.search(
            query=payload.query,
            limit=payload.limit,
            include_domains=payload.include_domains,
            country=payload.country,
            languages=payload.languages,
        )
    except FirecrawlClientError as exc:
        raise _provider_unavailable() from exc

    data = {
        "provider": "firecrawl",
        "query": payload.query,
        "request": {
            "limit": payload.limit,
            "include_domains": payload.include_domains,
            "country": payload.country,
            "languages": payload.languages,
        },
        "results": [
            {"url": item.url, "title": item.title, "description": item.description}
            for item in results
        ],
        "count": len(results),
        "ephemeral": True,
    }
    _assert_caller_still_active(session, caller)
    _write_external_search_audit(
        session, caller=caller, query=payload.query, provider="firecrawl",
        result_count=len(results), request=request,
    )
    return response(data, request)


@router.post("/web-search", response_model=schemas.ApiResponse[dict[str, Any]])
def search_web_search(
    payload: WebSearchExternalSearchRequest,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
    client: HttpWebSearchCustomClient = Depends(get_web_search_custom_client),
):
    """Retrieve provider content through Web Search without creating assets."""
    try:
        outcome = client.search(
            query=payload.query,
            count=payload.count,
            time_range=payload.time_range,
        )
    except WebSearchCustomError as exc:
        raise _provider_unavailable() from exc

    data = {
        "provider": "web_search",
        "query": payload.query,
        "request": {"count": payload.count, "time_range": payload.time_range},
        "results": [
            {
                "result_id": item.result_id,
                "title": item.title,
                "url": item.url,
                "content": item.content,
                "content_source": item.content_source,
                "metadata": item.metadata,
            }
            for item in outcome.items
        ],
        "count": len(outcome.items),
        "provider_request_id": outcome.request_id,
        "provider_log_id": outcome.log_id,
        "provider_time_cost_ms": outcome.time_cost_ms,
        "ephemeral": True,
    }
    _assert_caller_still_active(session, caller)
    _write_external_search_audit(
        session, caller=caller, query=payload.query, provider="web_search",
        result_count=len(outcome.items), request=request,
        provider_meta={
            "request_id": outcome.request_id,
            "log_id": outcome.log_id,
            "time_cost_ms": outcome.time_cost_ms,
        },
    )
    return response(data, request)
