from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from nexus_app import models, schemas
from nexus_app.config import Settings
from nexus_app.crawler import deepseek_search_client, service
from nexus_app.crawler.websearch_custom_client import WebSearchCustomItem, WebSearchCustomResponse
from nexus_app.pipeline.stages import _websearch_package_header
from nexus_app.storage import InMemoryObjectStorage


def test_deepseek_search_requests_content_and_parses_results(monkeypatch):
    monkeypatch.setattr(deepseek_search_client, "get_settings", lambda: SimpleNamespace(
        api_key_deepseek="test-key", base_url_deepseek="https://api.deepseek.com",
        crawler_websearch_custom_timeout_seconds=2,
    ))
    captured = {}

    class Client:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return httpx.Response(200, request=httpx.Request("POST", url), json={"results": [
                {"title": "政策", "url": "https://example.gov.cn/p", "content": "正文", "rerank_score": 2.1, "authority": 3},
                {"title": "无正文", "url": "https://example.gov.cn/empty", "content": "", "summary": "摘要"},
            ]})

    monkeypatch.setattr(deepseek_search_client.httpx, "Client", Client)
    outcome = deepseek_search_client.HttpDeepSeekSearchClient().search(
        query="电子商务 政策", count=10, time_range="2025-01-01..2026-01-01",
    )
    assert captured["url"] == "https://api.deepseek.com/v1/tools/search"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["payload"] == {"query": "电子商务 政策 after:2025-01-01 before:2026-01-01", "count": 10, "need_content": True}
    assert len(outcome.items) == 1
    assert outcome.items[0].metadata["RankScore"] == 2.1
    assert outcome.items[0].metadata["AuthInfoLevel"] == 3


@pytest.mark.parametrize(("title", "score", "authority", "reason"), [
    ("产业报告", 1.49, 4, None),
    ("产业政策", 1.5, 2, "low_authority"),
    ("产业政策", 0.2, 3, None),
    ("产业发展规划", 2.0, 2, "low_authority"),
    ("产业行动方案", 2.0, 3, None),
    ("产业报告", 1.5, 0, None),
    ("产业政策", None, 4, None),
])
def test_deepseek_result_thresholds(title, score, authority, reason):
    item = WebSearchCustomItem("id", title, "https://example.gov.cn/p", "正文" * 120,
                               "content", {"RankScore": score, "AuthInfoLevel": authority})
    assert service._deepseek_filter_reason(item) == reason


def test_deepseek_raw_package_uses_existing_document_route():
    package = {"schema_version": "websearch-custom-document.v1",
               "connector_type": "websearch", "connector_version": "deepseek",
               "provider": "deepseek_search", "content": "政策正文"}
    assert _websearch_package_header(json.dumps(package).encode()) == package


def test_deepseek_plan_filters_before_raw_ingest(session, monkeypatch):
    plan = service.create_plan(session, schemas.CrawlerPlanCreate(
        name="DeepSeek plan", connector_type="websearch", connector_version="deepseek",
        mode="custom", search_policy={"query": "电商政策", "result_count": 10, "time_range_preset": "one_year"},
    ))
    assert plan.connector_version == "deepseek"
    assert session.get(models.DataSource, plan.data_source_id).connection_config["provider"] == "deepseek_search"

    def item(title, score, authority, path):
        return WebSearchCustomItem(path, title, f"https://example.gov.cn/{path}",
                                   "电子商务市场与产业数据分析。" * 30, "content",
                                   {"RankScore": score, "AuthInfoLevel": authority})

    class Client:
        def search(self, **_kwargs):
            return WebSearchCustomResponse([
                item("产业报告", 1.4, 4, "low-score"),
                item("电子商务实施规划", 2.1, 2, "low-authority"),
                item("电子商务行动方案", 2.1, 3, "accepted"),
            ], None, None, None)

    monkeypatch.setattr(service, "HttpDeepSeekSearchClient", Client)
    run = service._run_websearch_custom_plan(
        session, plan, trace_id="trace-deepseek", storage=InMemoryObjectStorage(),
        settings=Settings(),
    )
    assert run.status == "succeeded"
    assert run.connector_version == "deepseek"
    assert run.summary["query_count"] == 1
    assert run.summary["filter_reasons"] == {"low_authority": 1}
    assert run.summary["submitted_count"] == 2
    assert {row["url"] for row in run.summary["submitted"]} == {
        "https://example.gov.cn/low-score", "https://example.gov.cn/accepted",
    }
