"""Tests for Open API external-search crawler ingestion."""
from __future__ import annotations

from nexus_app import models
from nexus_app.crawler.firecrawl_client import FirecrawlDocumentSnapshot
from nexus_app.crawler.open_search_ingest import ingest_websearch_items
from nexus_app.crawler.open_search_ingest import ingest_firecrawl_snapshots
from nexus_app.crawler.websearch_custom_client import WebSearchCustomItem
from nexus_app.enums import PipelineType
from nexus_app.storage import InMemoryObjectStorage


def _qualified_item() -> WebSearchCustomItem:
    return WebSearchCustomItem(
        result_id="result-1",
        title="产业市场报告",
        url="https://example.com/reports/industry-market",
        content="市场规模、产业链发展和年度统计数据分析。" * 20,
        content_source="content",
        metadata={"RankScore": 0.9},
    )


def test_open_websearch_ingest_queues_qualified_document(session):
    summary = ingest_websearch_items(
        session,
        [_qualified_item()],
        trace_id="trace-open-search",
        storage=InMemoryObjectStorage(),
    )

    assert summary["accepted_count"] == 1
    assert summary["submitted_count"] == 1
    assert summary["raw_persisted_count"] == 1
    raw = session.query(models.RawObject).one()
    job = session.query(models.Job).one()
    assert raw.metadata_summary["connector_type"] == "websearch_custom_document"
    assert raw.metadata_summary["origin"] == "open_external_search"
    assert raw.metadata_summary["filename"].startswith("产业市场报告-")
    assert raw.metadata_summary["filename"].endswith(".json")
    assert job.payload["pipeline_type"] == PipelineType.DOCUMENT.value


def test_open_firecrawl_ingest_queues_qualified_document(session):
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/policies/1",
        final_url="https://example.gov.cn/policies/1",
        title="产业政策实施方案",
        markdown="产业发展实施方案和具体政策措施。" * 20,
        html=None,
        metadata={},
    )

    summary = ingest_firecrawl_snapshots(
        session,
        [snapshot],
        trace_id="trace-open-search",
        storage=InMemoryObjectStorage(),
    )

    assert summary["submitted_count"] == 1
    raw = session.query(models.RawObject).one()
    job = session.query(models.Job).one()
    assert raw.metadata_summary["connector_type"] == "firecrawl_document"
    assert job.payload["pipeline_type"] == PipelineType.DOCUMENT.value


def test_open_websearch_ingest_filters_noise_without_persisting(session):
    noisy_item = WebSearchCustomItem(
        result_id="noise-1",
        title="首页",
        url="https://example.com/",
        content="内容过短",
        content_source="content",
        metadata={"RankScore": 0.01},
    )

    summary = ingest_websearch_items(
        session,
        [noisy_item],
        trace_id="trace-open-search",
        storage=InMemoryObjectStorage(),
    )

    assert summary["filter_reasons"] == {"homepage_or_channel": 1}
    assert summary["submitted_count"] == 0
    assert session.query(models.DataSource).count() == 0
    assert session.query(models.RawObject).count() == 0
    assert session.query(models.Job).count() == 0


def test_open_websearch_ingest_reuses_same_source_content(session):
    storage = InMemoryObjectStorage()
    first = ingest_websearch_items(
        session,
        [_qualified_item()],
        trace_id="trace-open-search-1",
        storage=storage,
    )
    second = ingest_websearch_items(
        session,
        [_qualified_item()],
        trace_id="trace-open-search-2",
        storage=storage,
    )

    assert first["duplicate_count"] == 0
    assert second["duplicate_count"] == 1
    assert session.query(models.RawObject).count() == 1
    assert session.query(models.Job).count() == 2
