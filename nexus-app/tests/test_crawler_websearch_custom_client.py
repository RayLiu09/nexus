from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from nexus_app.crawler import websearch_custom_client as module


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
