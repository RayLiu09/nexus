from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from nexus_app import models
from nexus_app.config import Settings
from nexus_app.crawler import service as crawler_service
from nexus_app.crawler import websearch_custom_client as module
from nexus_app.crawler.websearch_custom_client import (
    WebSearchCustomItem,
    WebSearchCustomResponse,
)
from nexus_app.enums import DataSourceStatus, DataSourceType
from nexus_app.storage import InMemoryObjectStorage


def _settings():
    return SimpleNamespace(
        crawler_websearch_custom_api_key="test-key",
        crawler_websearch_custom_api_endpoint="https://websearch.example/search",
        crawler_websearch_custom_timeout_seconds=2,
    )


def test_custom_client_requests_markdown_and_parses_direct_result(monkeypatch):
    monkeypatch.setattr(module, "get_settings", _settings)
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def post(self, _url, *, headers, json):
            captured.update({"headers": headers, "json": json})
            return httpx.Response(200, json={"ResponseMetadata":{"RequestId":"request-1"}, "Result":{"LogId":"log-1","TimeCost":12,"WebResults":[{"Id":"r-1","Title":"政策","Url":"https://example.gov.cn/p","Content":"# 政策","ContentFormats":"markdown","AuthInfoLevel":1}]}})

    monkeypatch.setattr(module.httpx, "Client", Client)
    outcome = module.HttpWebSearchCustomClient().search(query="电子商务", count=10, time_range="2026-01-01..2026-08-01")
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["json"]["ContentFormats"] == "markdown"
    assert outcome.request_id == "request-1"
    assert outcome.items[0].content == "# 政策"


def test_custom_client_accepts_nested_custom_search_response(monkeypatch):
    monkeypatch.setattr(module, "get_settings", _settings)
    class Client:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def post(self, *_args, **_kwargs):
            return httpx.Response(200, json={"ResponseMetadata":{}, "Result":{"CustomSearchResp":{"WebResults":[{"Id":"r-1","Url":"https://example.gov.cn/p","Summary":"# 摘要"}]}}})
    monkeypatch.setattr(module.httpx, "Client", Client)
    assert module.HttpWebSearchCustomClient().search(query="电子商务", count=10, time_range="OneYear").items[0].content_source == "summary"


@pytest.mark.parametrize("code", ["700429", "10406"])
def test_custom_client_classifies_api_errors(monkeypatch, code):
    monkeypatch.setattr(module, "get_settings", _settings)
    class Client:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def post(self, *_args, **_kwargs): return httpx.Response(200, json={"ResponseMetadata":{"Error":{"Code":code}}, "Result":None})
    monkeypatch.setattr(module.httpx, "Client", Client)
    with pytest.raises(module.WebSearchCustomError, match="provider_rate_limited" if code == "700429" else "provider_api_10406"):
        module.HttpWebSearchCustomClient().search(query="电子商务", count=10, time_range="OneYear")


def test_websearch_dedup_uses_stable_package_without_run_provenance(session, monkeypatch):
    """The same result in a later run must reuse its existing raw object."""
    source = models.DataSource(
        code="websearch-dedup",
        name="WebSearch dedup test",
        source_type=DataSourceType.CRAWLER,
        status=DataSourceStatus.ENABLED,
    )
    session.add(source)
    session.flush()
    plan = models.CrawlerPlan(
        name="WebSearch dedup plan",
        connector_type="websearch",
        connector_version="custom",
        mode="custom",
        data_source_id=source.id,
        execution_mode="run_once",
        search_policy={"query": "电子商务", "result_count": 10, "time_range_preset": "one_year"},
        pipeline_policy={"pipeline_type": "document"},
        status="active",
    )
    session.add(plan)
    session.commit()

    item = WebSearchCustomItem(
        result_id="result-1",
        title="2026年电子商务市场运行报告",
        url="https://example.gov.cn/reports/ecommerce-2026",
        content="电子商务产业市场规模持续增长，网络零售额和跨境电商进出口数据表现良好。" * 20,
        content_source="content",
        metadata={"RankScore": 0.9, "ContentFormats": "markdown"},
    )

    class FakeClient:
        calls = 0

        def search(self, **_kwargs):
            self.__class__.calls += 1
            call = self.__class__.calls
            return WebSearchCustomResponse(
                items=[item],
                request_id=f"request-{call}",
                log_id=f"log-{call}",
                time_cost_ms=10,
            )

    monkeypatch.setattr(crawler_service, "HttpWebSearchCustomClient", FakeClient)
    storage = InMemoryObjectStorage()
    settings = Settings()

    first = crawler_service._run_websearch_custom_plan(
        session, plan, trace_id="trace-1", storage=storage, settings=settings,
    )
    second = crawler_service._run_websearch_custom_plan(
        session, plan, trace_id="trace-2", storage=storage, settings=settings,
    )

    assert first.summary["submitted"][0]["duplicate"] is False
    assert second.summary["submitted"][0]["duplicate"] is True
    assert second.summary["duplicate_count"] == 1
    raw_objects = session.query(models.RawObject).all()
    assert len(raw_objects) == 1
    raw_key = raw_objects[0].object_uri.split("/", 3)[-1]
    raw_package = json.loads(storage.get_bytes(raw_key).decode("utf-8"))
    assert "provenance" not in raw_package
    assert raw_objects[0].metadata_summary["crawler_run_id"] == first.id
