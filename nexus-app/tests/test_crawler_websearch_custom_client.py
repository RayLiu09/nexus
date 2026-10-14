from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from botocore.exceptions import EndpointConnectionError

from nexus_app import models
from nexus_app.config import Settings
from nexus_app.crawler import service as crawler_service
from nexus_app.crawler import websearch_custom_client as module
from nexus_app.crawler.websearch_custom_client import (
    WebSearchCustomItem,
    WebSearchCustomResponse,
)
from nexus_app.enums import AuditEventType, DataSourceStatus, DataSourceType, IngestBatchStatus
from nexus_app.storage import InMemoryObjectStorage, ObjectStorageError


def _settings():
    return SimpleNamespace(
        crawler_websearch_custom_api_key="test-key",
        crawler_websearch_custom_api_endpoint="https://websearch.example/search",
        crawler_websearch_custom_timeout_seconds=2,
    )


def test_normalize_legacy_duplicate_status_as_success():
    run = SimpleNamespace(
        status="partial_failed",
        summary={
            "accepted_count": 2,
            "submitted_count": 2,
            "duplicate_count": 2,
            "failed_count": 2,
            "failures": [{"reason": "duplicate_raw_object"}, {"reason": "去重"}],
        },
    )
    assert crawler_service.normalize_crawler_run_status(run) is True
    assert run.status == "succeeded"
    assert run.summary["failed_count"] == 0
    assert run.summary["failures"] == []


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
    assert first.status == "succeeded"
    assert second.summary["submitted"][0]["duplicate"] is True
    assert second.summary["duplicate_count"] == 1
    assert second.summary["failed_count"] == 0
    assert second.summary["failures"] == []
    assert second.status == "succeeded"
    raw_objects = session.query(models.RawObject).all()
    assert len(raw_objects) == 1
    raw_key = raw_objects[0].object_uri.split("/", 3)[-1]
    raw_package = json.loads(storage.get_bytes(raw_key).decode("utf-8"))
    assert "provenance" not in raw_package
    assert raw_objects[0].metadata_summary["crawler_run_id"] == first.id


@pytest.mark.parametrize("fail_on", [1, 2])
def test_websearch_storage_failure_finishes_run_and_audits(session, monkeypatch, fail_on):
    source = models.DataSource(
        code=f"websearch-storage-{fail_on}", name="WebSearch storage failure",
        source_type=DataSourceType.CRAWLER, status=DataSourceStatus.ENABLED,
    )
    session.add(source)
    session.flush()
    plan = models.CrawlerPlan(
        name="WebSearch storage failure", connector_type="websearch",
        connector_version="custom", mode="custom", data_source_id=source.id,
        execution_mode="run_once",
        search_policy={"query":"电子商务", "result_count":10, "time_range_preset":"one_year"},
        pipeline_policy={"pipeline_type":"document"}, status="active",
    )
    session.add(plan)
    session.commit()

    class FakeClient:
        def search(self, **_kwargs):
            items = [WebSearchCustomItem(
                result_id=f"result-{index}", title=f"电子商务市场报告 {index}",
                url=f"https://example.gov.cn/reports/ecommerce-{index}",
                content="电子商务产业市场规模持续增长。" * 30,
                content_source="content", metadata={"RankScore":0.9},
            ) for index in (1, 2)]
            return WebSearchCustomResponse(items, "request-storage", None, 10)

    class FailingStorage(InMemoryObjectStorage):
        calls = 0

        def put_bytes(self, *args, **kwargs):
            self.calls += 1
            if self.calls == fail_on:
                if fail_on == 1:
                    raise EndpointConnectionError(endpoint_url="https://secret-storage.example")
                raise ObjectStorageError("secret storage endpoint")
            return super().put_bytes(*args, **kwargs)

    monkeypatch.setattr(crawler_service, "HttpWebSearchCustomClient", FakeClient)
    run = crawler_service._run_websearch_custom_plan(
        session, plan, trace_id="trace-storage", storage=FailingStorage(), settings=Settings(),
    )

    assert run.status == ("failed" if fail_on == 1 else "partial_failed")
    assert run.finished_at is not None
    assert run.summary["submitted_count"] == fail_on - 1
    assert run.summary["failures"] == [{"reason":"object_storage_unavailable"}]
    assert "secret-storage.example" not in str(run.summary)
    assert "secret storage endpoint" not in str(run.summary)
    assert session.query(models.RawObject).count() == fail_on - 1
    assert session.query(models.Job).count() == fail_on - 1
    batch = session.query(models.IngestBatch).filter_by(
        idempotency_key=f"crawler-run-{run.id}",
    ).one()
    assert batch.status == (IngestBatchStatus.FAILED if fail_on == 1 else IngestBatchStatus.RAW_PERSISTED)
    audit = session.query(models.AuditLog).filter_by(
        target_id=run.id, event_type=AuditEventType.CRAWLER_RUN_COMPLETED,
    ).one()
    assert audit.trace_id == "trace-storage"
    assert audit.summary["status"] == run.status


def test_websearch_successful_empty_response_is_no_results(session, monkeypatch):
    plan = models.CrawlerPlan(
        name="WebSearch empty response",
        connector_type="websearch",
        connector_version="custom",
        mode="custom",
        execution_mode="run_once",
        search_policy={"query": "电子商务", "result_count": 10, "time_range_preset": "one_year"},
        pipeline_policy={"pipeline_type": "document"},
        status="active",
    )
    session.add(plan)
    session.commit()

    class EmptyClient:
        def search(self, **_kwargs):
            return WebSearchCustomResponse(
                items=[],
                request_id="request-empty",
                log_id="log-empty",
                time_cost_ms=10,
            )

    monkeypatch.setattr(crawler_service, "HttpWebSearchCustomClient", EmptyClient)
    run = crawler_service._run_websearch_custom_plan(
        session,
        plan,
        trace_id="trace-empty",
        storage=InMemoryObjectStorage(),
        settings=Settings(),
    )

    assert run.status == "no_results"
    assert run.summary["result_count"] == 0
    assert run.summary["accepted_count"] == 0
    assert run.summary["filtered_count"] == 0
    assert run.summary["submitted_count"] == 0
    assert run.summary["failed_count"] == 0


@pytest.mark.parametrize("include_accepted", [False, True])
def test_websearch_normal_filters_do_not_fail_run(session, monkeypatch, include_accepted):
    source = models.DataSource(
        code=f"websearch-filter-{include_accepted}",
        name="WebSearch filter test",
        source_type=DataSourceType.CRAWLER,
        status=DataSourceStatus.ENABLED,
    )
    session.add(source)
    session.flush()
    plan = models.CrawlerPlan(
        name="WebSearch filter plan",
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

    filtered = WebSearchCustomItem(
        result_id="home",
        title="首页",
        url="https://example.gov.cn/",
        content="首页导航" * 50,
        content_source="content",
        metadata={},
    )
    accepted = WebSearchCustomItem(
        result_id="report",
        title="电子商务市场报告",
        url="https://example.gov.cn/reports/ecommerce",
        content="电子商务市场数据和行业分析。" * 30,
        content_source="content",
        metadata={},
    )

    class FakeClient:
        def search(self, **_kwargs):
            return WebSearchCustomResponse(
                items=[filtered, accepted] if include_accepted else [filtered],
                request_id="request-filter",
                log_id=None,
                time_cost_ms=10,
            )

    monkeypatch.setattr(crawler_service, "HttpWebSearchCustomClient", FakeClient)
    run = crawler_service._run_websearch_custom_plan(
        session, plan, trace_id="trace-filter",
        storage=InMemoryObjectStorage(), settings=Settings(),
    )

    assert run.status == ("succeeded" if include_accepted else "no_results")
    assert run.summary["filtered_count"] == 1
    assert run.summary["submitted_count"] == int(include_accepted)
    assert run.summary["failed_count"] == 0
    assert run.summary["failures"] == []
    assert run.summary["filter_reasons"] == {"homepage_or_channel": 1}


def test_websearch_query_combinations_accept_separators_and_deduplicate_terms():
    query = crawler_service._validate_websearch_query("浙江省，低空经济;政策 浙江省")
    assert crawler_service._websearch_queries(query) == [
        "浙江省低空经济政策", "浙江省低空经济", "浙江省政策",
        "低空经济政策", "浙江省", "低空经济", "政策",
    ]
    assert crawler_service._websearch_queries("电子商务") == ["电子商务"]
    with pytest.raises(crawler_service.CrawlerPlanError, match="1 to 4 unique terms"):
        crawler_service._validate_websearch_query("一 二 三 四 五")


def test_websearch_combines_results_by_url_and_keeps_partial_success(session, monkeypatch):
    source = models.DataSource(
        code="websearch-combinations", name="WebSearch combinations",
        source_type=DataSourceType.CRAWLER, status=DataSourceStatus.ENABLED,
    )
    session.add(source)
    session.flush()
    plan = models.CrawlerPlan(
        name="WebSearch combinations", connector_type="websearch",
        connector_version="custom", mode="custom", data_source_id=source.id,
        execution_mode="run_once",
        search_policy={"query": "电子商务 政策", "result_count": 10, "time_range_preset": "one_year"},
        pipeline_policy={"pipeline_type": "document"}, status="active",
    )
    session.add(plan)
    session.commit()
    item = WebSearchCustomItem(
        result_id="result-1", title="2026年电子商务市场运行报告",
        url="https://example.gov.cn/reports/ecommerce-2026",
        content="电子商务产业市场规模持续增长，网络零售额和跨境电商进出口数据表现良好。" * 20,
        content_source="content", metadata={"RankScore": 0.9},
    )

    class FakeClient:
        calls = []

        def search(self, *, query, **_kwargs):
            self.__class__.calls.append(query)
            if query == "政策":
                raise module.WebSearchCustomError("provider_rate_limited")
            return WebSearchCustomResponse(
                items=[item], request_id=f"request-{query}", log_id=None, time_cost_ms=10,
            )

    monkeypatch.setattr(crawler_service, "HttpWebSearchCustomClient", FakeClient)
    run = crawler_service._run_websearch_custom_plan(
        session, plan, trace_id="trace-combinations",
        storage=InMemoryObjectStorage(), settings=Settings(),
    )

    assert FakeClient.calls == ["电子商务政策", "电子商务", "政策"]
    assert run.status == "partial_failed"
    assert run.summary["result_count"] == 1
    assert run.summary["submitted_count"] == 1
    assert run.summary["search_failures"] == [
        {"query": "政策", "reason": "provider_rate_limited"}
    ]
    assert session.query(models.RawObject).count() == 1
