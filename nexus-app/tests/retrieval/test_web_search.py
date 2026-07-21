from __future__ import annotations

import json

import httpx

from nexus_app.retrieval.web_search import FirecrawlWebSearchClient, create_default_ai_web_search_client


def _client(handler) -> FirecrawlWebSearchClient:
    return FirecrawlWebSearchClient(
        endpoint="https://firecrawl.example/v2",
        api_key="test-key",
        timeout_seconds=1,
        max_results=5,
        transport=httpx.MockTransport(handler),
    )


def test_firecrawl_search_returns_request_scoped_result_metadata_only():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/search"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "query": "最新AI智能体的发展趋势", "limit": 5,
            "lang": "zh-CN", "country": "CN",
        }
        return httpx.Response(200, json={"data": {"web": [{
            "title": "AI agent report", "url": "https://example.org/report",
            "description": "Public search summary",
        }]}})

    outcome = _client(handler).search("最新AI智能体的发展趋势")

    assert outcome.warning is None
    assert outcome.provider == "firecrawl"
    assert outcome.domains == ["example.org"]
    assert outcome.results[0].to_api_dict()["source_type"] == "external_web"
    assert outcome.results[0].url == "https://example.org/report"


def test_sensitive_query_is_blocked_before_firecrawl_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"unexpected external request: {request.url}")

    outcome = _client(handler).search("API_KEY=secret-value 最新 AI 发展趋势")

    assert outcome.results == ()
    assert outcome.warning == "external_search_blocked_sensitive_query"
    assert outcome.error_type == "sensitive_query"


def test_provider_failure_never_raises_or_exposes_provider_body():
    outcome = _client(lambda request: httpx.Response(503, text="provider secret body")).search("AI 趋势")

    assert outcome.results == ()
    assert outcome.warning == "external_search_unavailable"
    assert outcome.error_type == "http_503"


def test_unregistered_provider_configuration_is_disabled(monkeypatch):
    monkeypatch.setattr("nexus_app.retrieval.web_search.get_settings", lambda: type("Settings", (), {
        "ai_web_search_provider": "future-provider",
    })())
    assert create_default_ai_web_search_client().__class__.__name__ == "DisabledAIWebSearchClient"
