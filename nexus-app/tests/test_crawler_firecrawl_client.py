from __future__ import annotations

import json

import httpx

from nexus_app.crawler.firecrawl_client import HttpFirecrawlDocumentClient


def _client(handler) -> HttpFirecrawlDocumentClient:
    return HttpFirecrawlDocumentClient(
        endpoint="https://firecrawl.example",
        api_key="test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def test_batch_scrape_uses_firecrawl_v2_top_level_options():
    captured_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/batch/scrape"
        assert request.headers["authorization"] == "Bearer test-key"
        captured_payload.update(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "id": "batch-001"})

    _client(handler).batch_scrape(
        urls=["https://example.org/a"],
        only_main_content=True,
        formats=["markdown", "html"],
        proxy="basic",
        max_concurrency=1,
        max_age_ms=172800000,
    )

    assert captured_payload == {
        "urls": ["https://example.org/a"],
        "formats": ["markdown", "html"],
        "onlyMainContent": True,
        "ignoreInvalidURLs": True,
        "proxy": "basic",
        "maxAge": 172800000,
        "maxConcurrency": 1,
    }
    assert "scrapeOptions" not in captured_payload


def test_single_scrape_uses_firecrawl_v2_top_level_options():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/scrape"
        assert json.loads(request.content) == {
            "url": "https://example.org/a",
            "formats": ["markdown"],
            "onlyMainContent": True,
            "proxy": "basic",
            "maxAge": 172800000,
        }
        return httpx.Response(
            200,
            json={
                "data": {
                    "markdown": "数字经济 " * 80,
                    "metadata": {
                        "sourceURL": "https://example.org/a",
                        "title": "数字经济政策",
                    },
                }
            },
        )

    snapshot = _client(handler).scrape(
        url="https://example.org/a",
        only_main_content=True,
        formats=["markdown"],
        proxy="basic",
        max_age_ms=172800000,
    )

    assert snapshot is not None
    assert snapshot.source_url == "https://example.org/a"
    assert snapshot.title == "数字经济政策"
