"""Contract tests for the distinct request-scoped external-search APIs."""
from __future__ import annotations

from datetime import date
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.api import external_search
from nexus_app import models
from nexus_app.crawler.firecrawl_client import FirecrawlClientError, FirecrawlSearchResult
from nexus_app.crawler.websearch_custom_client import WebSearchCustomItem, WebSearchCustomResponse
from nexus_app.crawler import deepseek_search_client
from nexus_app.enums import AuditEventType, PipelineType
from nexus_app.storage import InMemoryObjectStorage


@pytest.fixture(autouse=True)
def persisted_api_caller(session, stub_api_caller):
    # External search rechecks the persisted credential before returning results.
    session.add(stub_api_caller)
    session.commit()


class FakeFirecrawlClient:
    def search(self, **kwargs):
        self.kwargs = kwargs
        return [FirecrawlSearchResult(
            url="https://example.gov.cn/policy/1",
            title="政策文件",
            description="政策摘要",
        )]

    def scrape(self, **kwargs):
        self.scrape_kwargs = kwargs
        from nexus_app.crawler.firecrawl_client import FirecrawlDocumentSnapshot
        return FirecrawlDocumentSnapshot(
            source_url=kwargs["url"], final_url=kwargs["url"], title="政策文件",
            markdown="职业教育产教融合政策实施方案。" * 20, html=None, metadata={},
        )


class FakeWebSearchClient:
    def search(self, **kwargs):
        self.kwargs = kwargs
        return WebSearchCustomResponse(
            items=[WebSearchCustomItem(
                result_id="web-1", title="市场报告", url="https://example.com/report",
                content=("# 报告正文\n跨境电商市场运行数据与产业规模分析。" * 20), content_source="content",
                metadata={"SiteName": "示例站点", "RankScore": 0.9},
            )],
            request_id="request-1", log_id="log-1", time_cost_ms=15,
        )


def test_firecrawl_external_search_keeps_discovery_shape_and_audits(app, session):
    client = FakeFirecrawlClient()
    app.dependency_overrides[external_search.get_firecrawl_document_client] = lambda: client
    app.dependency_overrides[external_search.get_external_search_storage] = InMemoryObjectStorage
    with TestClient(app) as http:
        result = http.post("/open/v1/external-search/firecrawl", json={
            "query": "跨境电商 政策", "limit": 3, "include_domains": ["example.gov.cn"],
        })

    assert result.status_code == 200
    data = result.json()["data"]
    assert data["provider"] == "firecrawl"
    assert data["results"] == [{
        "url": "https://example.gov.cn/policy/1", "title": "政策文件", "description": "政策摘要",
    }]
    assert "content" not in data["results"][0]
    assert data["ephemeral"] is True
    assert data["auto_ingest"] is True
    assert data["ingestion"]["submitted_count"] == 1
    assert session.query(models.RawObject).count() == 1
    assert session.query(models.Job).count() == 1
    raw = session.query(models.RawObject).one()
    job = session.query(models.Job).one()
    assert raw.metadata_summary["connector_type"] == "firecrawl_document"
    assert job.payload["pipeline_type"] == PipelineType.DOCUMENT.value
    assert client.kwargs["include_domains"] == ["example.gov.cn"]
    audit = session.scalars(
        select(models.AuditLog).order_by(models.AuditLog.created_at.desc())
    ).first()
    assert audit.event_type == AuditEventType.SEARCH_QUERY_EXECUTED
    assert audit.summary["route"] == "external_search_firecrawl"
    assert audit.summary["external_result_ephemeral"] is True
    assert "跨境电商" not in str(audit.summary)
    assert "职业教育" not in str(audit.summary)


def test_web_search_external_search_keeps_content_shape_and_audits(app, session):
    client = FakeWebSearchClient()
    app.dependency_overrides[external_search.get_deepseek_search_client] = lambda: client
    app.dependency_overrides[external_search.get_external_search_storage] = InMemoryObjectStorage
    with TestClient(app) as http:
        result = http.post("/open/v1/external-search/web-search", json={
            "query": "跨境电商 市场报告", "count": 5, "time_range": "OneMonth",
        })

    assert result.status_code == 200
    data = result.json()["data"]
    assert data["provider"] == "deepseek_search"
    assert data["results"][0]["content"].startswith("# 报告正文")
    assert data["results"][0]["content_source"] == "content"
    assert data["provider_request_id"] == "request-1"
    assert data["ephemeral"] is True
    assert data["auto_ingest"] is True
    assert data["ingestion"]["submitted_count"] == 1
    assert session.query(models.RawObject).count() == 1
    assert session.query(models.Job).count() == 1
    raw = session.query(models.RawObject).one()
    job = session.query(models.Job).one()
    assert raw.metadata_summary["connector_type"] == "websearch_custom_document"
    assert job.payload["pipeline_type"] == PipelineType.DOCUMENT.value
    assert client.kwargs == {"query": "跨境电商 市场报告", "count": 5, "time_range": data["request"]["resolved_time_range"]}
    assert data["request"]["time_range"] == "OneMonth"
    assert raw.metadata_summary["connector_version"] == "deepseek"
    assert raw.metadata_summary["content_format"] == "text"
    assert raw.metadata_summary["provider"] == "deepseek_search"
    audit = session.scalars(
        select(models.AuditLog).order_by(models.AuditLog.created_at.desc())
    ).first()
    assert audit.summary["route"] == "external_search_deepseek_search"
    assert audit.summary["provider_meta"]["request_id"] == "request-1"
    assert "市场运行数据" not in str(audit.summary)


def test_web_search_filters_unqualified_results_without_creating_assets(app, session):
    class LowQualityClient:
        def search(self, **kwargs):
            return WebSearchCustomResponse(
                items=[WebSearchCustomItem(
                    result_id="low-1", title="首页", url="https://example.com/",
                    content="太短", content_source="content", metadata={"RankScore": 0.01},
                )], request_id=None, log_id=None, time_cost_ms=None,
            )

    app.dependency_overrides[external_search.get_deepseek_search_client] = LowQualityClient
    app.dependency_overrides[external_search.get_external_search_storage] = InMemoryObjectStorage
    with TestClient(app) as http:
        result = http.post("/open/v1/external-search/web-search", json={"query": "产业政策"})

    assert result.status_code == 200
    assert result.json()["data"]["ingestion"] == {
        "candidate_count": 1, "accepted_count": 0, "filtered_count": 1,
        "filter_reasons": {"homepage_or_channel": 1}, "submitted_count": 0,
        "raw_persisted_count": 0, "duplicate_count": 0, "ingest_failed_count": 0,
        "ingest_failures": [], "submitted": [],
    }
    assert session.query(models.RawObject).count() == 0


def test_web_search_reuses_existing_raw_object_for_repeated_result(app, session):
    client = FakeWebSearchClient()
    app.dependency_overrides[external_search.get_deepseek_search_client] = lambda: client
    app.dependency_overrides[external_search.get_external_search_storage] = InMemoryObjectStorage
    with TestClient(app) as http:
        first = http.post("/open/v1/external-search/web-search", json={"query": "市场报告"})
        second = http.post("/open/v1/external-search/web-search", json={"query": "市场报告"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["ingestion"]["duplicate_count"] == 0
    assert second.json()["data"]["ingestion"]["duplicate_count"] == 1
    assert session.query(models.RawObject).count() == 1
    assert session.query(models.Job).count() == 2


def test_external_search_blocks_sensitive_query_before_provider_call(app):
    with TestClient(app) as http:
        result = http.post("/open/v1/external-search/firecrawl", json={
            "query": "token: sk-abcdefghijklmnopqrstuvwxyz",
        })
    assert result.status_code == 422


def test_external_search_auto_ingest_defaults_to_enabled():
    assert external_search.FirecrawlExternalSearchRequest(query="产业政策").auto_ingest is True
    assert external_search.WebSearchExternalSearchRequest(
        query="产业政策",
        auto_ingest=False,
    ).auto_ingest is False


def test_external_search_maps_provider_failure_without_exposing_configuration(app):
    class FailingClient:
        def search(self, **kwargs):
            del kwargs
            raise FirecrawlClientError("firecrawl timeout")

    app.dependency_overrides[external_search.get_firecrawl_document_client] = FailingClient
    with TestClient(app) as http:
        result = http.post("/open/v1/external-search/firecrawl", json={"query": "产业政策"})
    assert result.status_code == 503
    assert result.json()["error"]["message"] == "external_search_unavailable"


def test_default_web_search_calls_deepseek_wire_and_read_only_mode(app, session, monkeypatch):
    captured = {}
    real_client = httpx.Client

    def handle(request):
        captured.update(url=str(request.url), auth=request.headers["authorization"], body=json.loads(request.content))
        return httpx.Response(200, json={"results": [{
            "url": "https://example.gov.cn/reports/1", "title": "产业报告",
            "content": "报告正文", "authority": 3, "rerank_score": 0.1,
        }]})

    monkeypatch.setattr(deepseek_search_client, "get_settings", lambda: SimpleNamespace(
        api_key_deepseek="test-deepseek-key", base_url_deepseek="https://search.example.test",
        crawler_websearch_custom_timeout_seconds=2,
    ))
    monkeypatch.setattr(deepseek_search_client.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs,
    ))
    storage = InMemoryObjectStorage()
    app.dependency_overrides[external_search.get_external_search_storage] = lambda: storage
    result = TestClient(app).post("/open/v1/external-search/web-search", json={
        "query": "电商产业报告", "count": 3, "time_range": "2025-01-01..2026-01-01", "auto_ingest": False,
    })
    assert result.status_code == 200, result.text
    assert captured == {
        "url": "https://search.example.test/v1/tools/search", "auth": "Bearer test-deepseek-key",
        "body": {"query": "电商产业报告 after:2025-01-01 before:2026-01-01", "count": 3, "need_content": True},
    }
    data = result.json()["data"]
    assert data["provider"] == "deepseek_search"
    assert data["results"][0]["content"] == "报告正文"
    assert data["ingestion"]["enabled"] is False
    assert not storage.objects
    assert session.query(models.RawObject).count() == session.query(models.Job).count() == 0
    assert session.query(models.DataSource).count() == 0
    assert "test-deepseek-key" not in result.text
    audit = session.query(models.AuditLog).one()
    assert audit.summary["provider"] == "deepseek_search"
    assert "电商产业报告" not in str(audit.summary) and "test-deepseek-key" not in str(audit.summary)


@pytest.mark.parametrize("value,expected", [
    ("OneDay", "2026-02-28..2026-03-01"),
    ("OneWeek", "2026-02-22..2026-03-01"),
    ("OneMonth", "2026-01-30..2026-03-01"),
    ("OneYear", "2025-03-01..2026-03-01"),
    ("2024-02-29..2024-03-01", "2024-02-29..2024-03-01"),
])
def test_deepseek_date_range_presets_and_leap_day(value, expected):
    assert external_search._deepseek_time_range(value, today=date(2026, 3, 1)) == expected


@pytest.mark.parametrize("payload", [
    {"query": "词" * 91}, {"query": "   "}, {"query": "token: private-value"},
    {"query": "报告", "count": 51},
    {"query": "报告", "time_range": "AllTime"},
    {"query": "报告", "time_range": "2025-02-29..2026-01-01"},
    {"query": "报告", "time_range": "2026-01-02..2026-01-01"},
    {"query": "报告", "time_range": "2026-1-1..2026-01-02"},
])
def test_web_search_rejects_invalid_input_before_search(app, payload):
    client = FakeWebSearchClient()
    app.dependency_overrides[external_search.get_deepseek_search_client] = lambda: client
    result = TestClient(app).post("/open/v1/external-search/web-search", json=payload)
    assert result.status_code == 422, result.text
    assert not hasattr(client, "kwargs")


def test_deepseek_missing_credentials_returns_redacted_503(app, monkeypatch):
    monkeypatch.setattr(deepseek_search_client, "get_settings", lambda: SimpleNamespace(api_key_deepseek=None))
    result = TestClient(app).post("/open/v1/external-search/web-search", json={"query": "政策", "auto_ingest": False})
    assert result.status_code == 503
    assert result.json()["error"]["message"] == "external_search_unavailable"
    assert "API_KEY" not in result.text and "configured" not in result.text


def test_deepseek_upstream_failure_is_redacted(app):
    from nexus_app.crawler.websearch_custom_client import WebSearchCustomError

    class FailingDeepSeekClient:
        def search(self, **kwargs):
            raise WebSearchCustomError("provider_http_429 secret=test-key")

    app.dependency_overrides[external_search.get_deepseek_search_client] = FailingDeepSeekClient
    result = TestClient(app).post("/open/v1/external-search/web-search", json={"query": "政策"})
    assert result.status_code == 503
    assert result.json()["error"]["message"] == "external_search_unavailable"
    assert "test-key" not in result.text


def test_web_search_requires_api_caller_authentication(app_no_auth_override):
    result = TestClient(app_no_auth_override).post("/open/v1/external-search/web-search", json={"query": "政策"})
    assert result.status_code == 401
