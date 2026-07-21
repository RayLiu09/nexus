"""Request-scoped public-web fallback for Query Router v2.

This adapter deliberately has no database, cache, or ingestion dependency.
External search results are non-governed display material and must remain
separate from NEXUS chunks, citations, and model context.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from nexus_app.config import get_settings


_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_ -]?key|secret|token|password)\s*[:=]"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._-]+"),
    re.compile(r"\bsk-[a-zA-Z0-9_-]{12,}\b"),
    re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\\\)"),
    re.compile(r"\b(?:身份证号?|手机号?|客户(?:名称|编号)|内部项目)\s*[:：]"),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{17}[\dXx]\b"),
)


@dataclass(frozen=True)
class ExternalWebResult:
    """A provider result safe to return as ungoverned public-web material."""

    provider: str
    title: str
    url: str
    domain: str
    snippet: str | None
    published_at: str | None
    retrieved_at: str
    rank: int

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "source_type": "external_web",
            "provider": self.provider,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "snippet": self.snippet,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class WebSearchOutcome:
    results: tuple[ExternalWebResult, ...] = ()
    warning: str | None = None
    provider: str | None = None
    latency_ms: float | None = None
    error_type: str | None = None

    @property
    def domains(self) -> list[str]:
        return sorted({item.domain for item in self.results if item.domain})


class AIWebSearchClient(Protocol):
    def search(self, query: str) -> WebSearchOutcome: ...


class DisabledAIWebSearchClient:
    """Safe default when no provider is configured."""

    def search(self, query: str) -> WebSearchOutcome:
        del query
        return WebSearchOutcome(
            warning="external_search_unavailable",
            error_type="not_configured",
        )


class FirecrawlWebSearchClient:
    """Firecrawl v2 Search adapter.

    The endpoint and credential are deployment configuration. This class only
    sends the screened user query and returns Firecrawl search metadata; it
    never forwards local retrieval data to the provider.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: float,
        max_results: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_results = max_results
        self._transport = transport

    def search(self, query: str) -> WebSearchOutcome:
        if _has_sensitive_outbound_content(query):
            return WebSearchOutcome(
                warning="external_search_blocked_sensitive_query",
                error_type="sensitive_query",
            )

        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(
                    _firecrawl_search_url(self._endpoint),
                    headers={"authorization": f"Bearer {self._api_key}"},
                    json={
                        "query": query,
                        "limit": self._max_results,
                        "lang": "zh-CN",
                        "country": "CN",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException:
            return _failed_outcome("timeout", started)
        except httpx.HTTPStatusError as exc:
            return _failed_outcome(f"http_{exc.response.status_code}", started)
        except (httpx.HTTPError, ValueError, TypeError):
            return _failed_outcome("provider_error", started)

        return WebSearchOutcome(
            results=tuple(_parse_firecrawl_sources(payload, self._max_results)),
            provider="firecrawl",
            latency_ms=_elapsed_ms(started),
        )


def create_default_ai_web_search_client() -> AIWebSearchClient:
    settings = get_settings()
    factory = _WEB_SEARCH_PROVIDER_FACTORIES.get(settings.ai_web_search_provider)
    if factory is None:
        return DisabledAIWebSearchClient()
    return factory(settings)


def _create_firecrawl_client(settings: Any) -> AIWebSearchClient:
    if not (settings.firecrawl_api_endpoint and settings.firecrawl_api_key):
        return DisabledAIWebSearchClient()
    return FirecrawlWebSearchClient(
        endpoint=settings.firecrawl_api_endpoint,
        api_key=settings.firecrawl_api_key,
        timeout_seconds=settings.ai_web_search_timeout_seconds,
        max_results=settings.ai_web_search_max_results,
    )


_WEB_SEARCH_PROVIDER_FACTORIES = {
    "firecrawl": _create_firecrawl_client,
}


def _parse_firecrawl_sources(payload: Any, max_results: int) -> list[ExternalWebResult]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        candidates = data.get("web") or data.get("results") or []
    else:
        candidates = data or []
    if not isinstance(candidates, list):
        return []

    results: list[ExternalWebResult] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url") or candidate.get("source_url") or "").strip()
        if not url or url in seen_urls:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        seen_urls.add(url)
        results.append(ExternalWebResult(
            provider="firecrawl",
            title=str(candidate.get("title") or parsed.netloc).strip()[:300],
            url=url,
            domain=parsed.netloc.lower(),
            snippet=_clean_optional_text(
                candidate.get("snippet")
                or candidate.get("description")
                or candidate.get("text"),
            ),
            published_at=_clean_optional_text(candidate.get("published_at")),
            retrieved_at=datetime.now(UTC).isoformat(),
            rank=len(results) + 1,
        ))
        if len(results) >= max_results:
            break
    return results


def _clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:1000] if text else None


def _has_sensitive_outbound_content(query: str) -> bool:
    return any(pattern.search(query) for pattern in _SENSITIVE_PATTERNS)


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 2)


def _failed_outcome(error_type: str, started: float) -> WebSearchOutcome:
    return WebSearchOutcome(
        warning="external_search_unavailable",
        provider="firecrawl",
        latency_ms=_elapsed_ms(started),
        error_type=error_type,
    )


def _firecrawl_search_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    return f"{base}/search" if base.endswith("/v2") else f"{base}/v2/search"


__all__ = [
    "AIWebSearchClient",
    "DisabledAIWebSearchClient",
    "ExternalWebResult",
    "FirecrawlWebSearchClient",
    "WebSearchOutcome",
    "create_default_ai_web_search_client",
]
