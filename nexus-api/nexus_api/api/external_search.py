"""Request-scoped public-web search endpoints for API callers.

Firecrawl discovery and DeepSeek Search deliberately expose
separate contracts. Qualifying results are queued through the existing crawler
ingest pipeline; neither endpoint writes governed assets synchronously.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
import re
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
from nexus_app.crawler.deepseek_search_client import HttpDeepSeekSearchClient
from nexus_app.crawler.open_search_ingest import (
    ingest_firecrawl_snapshots,
    ingest_websearch_items,
)
from nexus_app.crawler.websearch_custom_client import WebSearchCustomError
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType
from nexus_app.retrieval.web_search import _has_sensitive_outbound_content
from nexus_app.storage import ObjectStorage, get_object_storage


router = APIRouter(
    prefix="/open/v1/external-search",
    dependencies=[Depends(require_api_caller)],
)


class _ExternalSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1024)
    auto_ingest: bool = Field(
        default=True,
        description="Queue qualifying results into the NEXUS crawler pipeline.",
    )

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
    query: str = Field(..., min_length=1, max_length=90,
                       description="DeepSeek 搜索词，最多 90 字符；服务端追加日期条件，不发送内部检索材料。")
    count: int = Field(default=10, ge=1, le=50)
    time_range: str = Field(default="OneYear", max_length=64,
        pattern=r"^(OneDay|OneWeek|OneMonth|OneYear|\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2})$",
        description="UTC 日期范围：OneDay/OneWeek/OneMonth/OneYear（分别近 1/7/30/365 天）或 YYYY-MM-DD..YYYY-MM-DD；起始日期不得晚于结束日期。")

    @field_validator("time_range")
    @classmethod
    def validate_time_range(cls, value: str) -> str:
        _deepseek_time_range(value)
        return value


def _deepseek_time_range(value: str, *, today: date | None = None) -> str:
    days = {"OneDay": 1, "OneWeek": 7, "OneMonth": 30, "OneYear": 365}
    if value in days:
        end = today or datetime.now(timezone.utc).date()
        start = end - timedelta(days=days[value])
    else:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}", value):
            raise ValueError("unsupported time_range")
        start_text, end_text = value.split("..", 1)
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        if start > end:
            raise ValueError("time_range start must not be after end")
    return f"{start.isoformat()}..{end.isoformat()}"


def get_firecrawl_document_client() -> FirecrawlDocumentClient:
    return create_default_firecrawl_document_client()


def get_deepseek_search_client() -> HttpDeepSeekSearchClient:
    return HttpDeepSeekSearchClient()


def get_external_search_storage() -> ObjectStorage:
    return get_object_storage()


def _provider_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="external_search_unavailable")


def _disabled_ingestion_summary() -> dict[str, Any]:
    return {
        "enabled": False,
        "candidate_count": 0,
        "accepted_count": 0,
        "filtered_count": 0,
        "submitted_count": 0,
        "raw_persisted_count": 0,
        "duplicate_count": 0,
        "scrape_failed_count": 0,
    }


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
    storage: ObjectStorage = Depends(get_external_search_storage),
):
    """Discover, quality-check, and queue qualifying Firecrawl documents."""
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

    ingestion = _disabled_ingestion_summary()
    scrape_failed_count = 0
    if payload.auto_ingest:
        snapshots = []
        for item in results:
            try:
                snapshot = client.scrape(
                    url=item.url,
                    only_main_content=True,
                    formats=["markdown", "html"],
                    proxy=None,
                    max_age_ms=None,
                )
            except FirecrawlClientError:
                scrape_failed_count += 1
                continue
            if snapshot is not None:
                snapshots.append(snapshot)
            else:
                scrape_failed_count += 1
        ingestion = ingest_firecrawl_snapshots(
            session,
            snapshots,
            trace_id=getattr(request.state, "trace_id", None),
            storage=storage,
        )
        ingestion["scrape_failed_count"] = scrape_failed_count
    data = {
        "provider": "firecrawl",
        "query": payload.query,
        "request": {
            "limit": payload.limit,
            "include_domains": payload.include_domains,
            "country": payload.country,
            "languages": payload.languages,
            "auto_ingest": payload.auto_ingest,
        },
        "results": [
            {"url": item.url, "title": item.title, "description": item.description}
            for item in results
        ],
        "count": len(results),
        "ephemeral": True,
        "auto_ingest": payload.auto_ingest,
        "ingestion": ingestion,
    }
    _assert_caller_still_active(session, caller)
    _write_external_search_audit(
        session,
        caller=caller,
        query=payload.query,
        provider="firecrawl",
        result_count=len(results),
        request=request,
        provider_meta={
            "auto_ingest": payload.auto_ingest,
            "ingestion": {
                key: ingestion[key]
                for key in (
                    "accepted_count",
                    "filtered_count",
                    "submitted_count",
                    "duplicate_count",
                    "scrape_failed_count",
                )
            }
        },
    )
    return response(data, request)


@router.post("/web-search", response_model=schemas.ApiResponse[dict[str, Any]])
def search_web_search(
    payload: WebSearchExternalSearchRequest,
    request: Request,
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
    client: HttpDeepSeekSearchClient = Depends(get_deepseek_search_client),
    storage: ObjectStorage = Depends(get_external_search_storage),
):
    """使用 DeepSeek Search 联网搜索，返回带来源链接的正文结果，支持结果数量及日期范围。

    服务端请求 need_content=true；query 最长 90 字符，日期预设会转换为 UTC 起止日期。
    凭证由服务器配置，未配置或上游失败返回 503，不切换其他供应商。
    auto_ingest=true 时，经 URL/正文质量及正式文件 authority>=3 检查后排队进入文档管道；
    rerank_score 仅作诊断。auto_ingest=false 时只返回临时搜索结果，不入库。
    """
    resolved_time_range = _deepseek_time_range(payload.time_range)
    try:
        outcome = client.search(
            query=payload.query,
            count=payload.count,
            time_range=resolved_time_range,
        )
    except WebSearchCustomError as exc:
        raise _provider_unavailable() from exc

    ingestion = _disabled_ingestion_summary()
    if payload.auto_ingest:
        ingestion = ingest_websearch_items(
            session,
            outcome.items,
            connector_version="deepseek",
            trace_id=getattr(request.state, "trace_id", None),
            storage=storage,
        )
    data = {
        "provider": "deepseek_search",
        "query": payload.query,
        "request": {
            "count": payload.count,
            "time_range": payload.time_range,
            "resolved_time_range": resolved_time_range,
            "auto_ingest": payload.auto_ingest,
        },
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
        "auto_ingest": payload.auto_ingest,
        "ingestion": ingestion,
    }
    _assert_caller_still_active(session, caller)
    _write_external_search_audit(
        session,
        caller=caller,
        query=payload.query,
        provider="deepseek_search",
        result_count=len(outcome.items),
        request=request,
        provider_meta={
            "auto_ingest": payload.auto_ingest,
            "request_id": outcome.request_id,
            "log_id": outcome.log_id,
            "time_cost_ms": outcome.time_cost_ms,
            "ingestion": {
                key: ingestion[key]
                for key in (
                    "accepted_count",
                    "filtered_count",
                    "submitted_count",
                    "duplicate_count",
                )
            },
        },
    )
    return response(data, request)
