"""Contract tests for the distinct request-scoped external-search APIs."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.api import external_search
from nexus_app import models
from nexus_app.crawler.firecrawl_client import FirecrawlClientError, FirecrawlSearchResult
from nexus_app.crawler.websearch_custom_client import WebSearchCustomItem, WebSearchCustomResponse
from nexus_app.enums import AuditEventType


class FakeFirecrawlClient:
    def search(self, **kwargs):
        self.kwargs = kwargs
        return [FirecrawlSearchResult(
            url="https://example.gov.cn/policy/1",
            title="政策文件",
            description="政策摘要",
        )]


class FakeWebSearchClient:
    def search(self, **kwargs):
        self.kwargs = kwargs
        return WebSearchCustomResponse(
            items=[WebSearchCustomItem(
                result_id="web-1", title="市场报告", url="https://example.com/report",
                content="# 报告正文", content_source="content",
                metadata={"SiteName": "示例站点", "RankScore": 0.9},
            )],
            request_id="request-1", log_id="log-1", time_cost_ms=15,
        )


def test_firecrawl_external_search_keeps_discovery_shape_and_audits(app, session):
    client = FakeFirecrawlClient()
    app.dependency_overrides[external_search.get_firecrawl_document_client] = lambda: client
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
    assert client.kwargs["include_domains"] == ["example.gov.cn"]
    audit = session.scalars(select(models.AuditLog).order_by(models.AuditLog.created_at.desc())).first()
    assert audit.event_type == AuditEventType.SEARCH_QUERY_EXECUTED
    assert audit.summary["route"] == "external_search_firecrawl"
    assert audit.summary["external_result_ephemeral"] is True
    assert "跨境电商" not in str(audit.summary)


def test_web_search_external_search_keeps_content_shape_and_audits(app, session):
    client = FakeWebSearchClient()
    app.dependency_overrides[external_search.get_web_search_custom_client] = lambda: client
    with TestClient(app) as http:
        result = http.post("/open/v1/external-search/web-search", json={
            "query": "跨境电商 市场报告", "count": 5, "time_range": "OneMonth",
        })

    assert result.status_code == 200
    data = result.json()["data"]
    assert data["provider"] == "web_search"
    assert data["results"][0]["content"] == "# 报告正文"
    assert data["results"][0]["content_source"] == "content"
    assert data["provider_request_id"] == "request-1"
    assert client.kwargs == {"query": "跨境电商 市场报告", "count": 5, "time_range": "OneMonth"}
    audit = session.scalars(select(models.AuditLog).order_by(models.AuditLog.created_at.desc())).first()
    assert audit.summary["route"] == "external_search_web_search"
    assert audit.summary["provider_meta"]["request_id"] == "request-1"


def test_external_search_blocks_sensitive_query_before_provider_call(app):
    with TestClient(app) as http:
        result = http.post("/open/v1/external-search/firecrawl", json={
            "query": "token: sk-abcdefghijklmnopqrstuvwxyz",
        })
    assert result.status_code == 422


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
