from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from nexus_app.config import get_settings


class FirecrawlClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirecrawlSearchResult:
    url: str
    title: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class FirecrawlDocumentSnapshot:
    source_url: str
    final_url: str
    title: str | None
    markdown: str | None
    html: str | None
    metadata: dict[str, Any]

    @property
    def text_for_quality(self) -> str:
        return self.markdown or self.html or ""


class FirecrawlDocumentClient(Protocol):
    def search(
        self,
        *,
        query: str,
        limit: int,
        include_domains: list[str] | None,
        country: str,
        languages: list[str],
    ) -> list[FirecrawlSearchResult]: ...

    def batch_scrape(
        self,
        *,
        urls: list[str],
        only_main_content: bool,
        formats: list[str],
        proxy: str | None,
        max_concurrency: int | None,
        max_age_ms: int | None,
    ) -> list[FirecrawlDocumentSnapshot]: ...

    def scrape(
        self,
        *,
        url: str,
        only_main_content: bool,
        formats: list[str],
        proxy: str | None,
        max_age_ms: int | None,
    ) -> FirecrawlDocumentSnapshot | None: ...


class DisabledFirecrawlDocumentClient:
    def search(
        self,
        *,
        query: str,
        limit: int,
        include_domains: list[str] | None,
        country: str,
        languages: list[str],
    ) -> list[FirecrawlSearchResult]:
        del query, limit, include_domains, country, languages
        raise FirecrawlClientError("firecrawl document client is not configured")

    def batch_scrape(
        self,
        *,
        urls: list[str],
        only_main_content: bool,
        formats: list[str],
        proxy: str | None,
        max_concurrency: int | None,
        max_age_ms: int | None,
    ) -> list[FirecrawlDocumentSnapshot]:
        del urls, only_main_content, formats, proxy, max_concurrency, max_age_ms
        raise FirecrawlClientError("firecrawl document client is not configured")

    def scrape(
        self,
        *,
        url: str,
        only_main_content: bool,
        formats: list[str],
        proxy: str | None,
        max_age_ms: int | None,
    ) -> FirecrawlDocumentSnapshot | None:
        del url, only_main_content, formats, proxy, max_age_ms
        raise FirecrawlClientError("firecrawl document client is not configured")


class HttpFirecrawlDocumentClient:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def search(
        self,
        *,
        query: str,
        limit: int,
        include_domains: list[str] | None,
        country: str,
        languages: list[str],
    ) -> list[FirecrawlSearchResult]:
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "country": country,
            "scrapeOptions": {
                "location": {
                    "languages": languages,
                }
            },
        }
        if include_domains:
            payload["includeDomains"] = include_domains
        data = self._post_json("/v2/search", payload)
        return _parse_search_results(data)

    def batch_scrape(
        self,
        *,
        urls: list[str],
        only_main_content: bool,
        formats: list[str],
        proxy: str | None,
        max_concurrency: int | None,
        max_age_ms: int | None,
    ) -> list[FirecrawlDocumentSnapshot]:
        if not urls:
            return []
        payload: dict[str, Any] = {
            "urls": urls,
            "formats": formats,
            "onlyMainContent": only_main_content,
            "ignoreInvalidURLs": True,
        }
        payload.update(_scrape_options(proxy=proxy, max_age_ms=max_age_ms))
        if max_concurrency is not None:
            payload["maxConcurrency"] = max_concurrency
        data = self._post_json(
            "/v2/batch/scrape",
            payload,
        )
        return _parse_batch_scrape_results(data, urls)

    def scrape(
        self,
        *,
        url: str,
        only_main_content: bool,
        formats: list[str],
        proxy: str | None,
        max_age_ms: int | None,
    ) -> FirecrawlDocumentSnapshot | None:
        payload: dict[str, Any] = {
            "url": url,
            "formats": formats,
            "onlyMainContent": only_main_content,
        }
        payload.update(_scrape_options(proxy=proxy, max_age_ms=max_age_ms))
        data = self._post_json("/v2/scrape", payload)
        return _parse_scrape_result(data, url)

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._endpoint}{path}",
                    headers={"authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise FirecrawlClientError("firecrawl timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise FirecrawlClientError(f"firecrawl http_{exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise FirecrawlClientError("firecrawl provider_error") from exc


def create_default_firecrawl_document_client() -> FirecrawlDocumentClient:
    settings = get_settings()
    if not (settings.firecrawl_api_endpoint and settings.firecrawl_api_key):
        return DisabledFirecrawlDocumentClient()
    return HttpFirecrawlDocumentClient(
        endpoint=settings.firecrawl_api_endpoint,
        api_key=settings.firecrawl_api_key,
        timeout_seconds=settings.ai_web_search_timeout_seconds,
    )


def _parse_search_results(payload: Any) -> list[FirecrawlSearchResult]:
    candidates = _extract_data_list(payload)
    results: list[FirecrawlSearchResult] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("source_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(
            FirecrawlSearchResult(
                url=url,
                title=_optional_text(item.get("title")),
                description=_optional_text(item.get("description") or item.get("snippet")),
            )
        )
    return results


def _scrape_options(
    *,
    proxy: str | None,
    max_age_ms: int | None,
) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if proxy:
        options["proxy"] = proxy
    if max_age_ms is not None:
        options["maxAge"] = max_age_ms
    return options


def _parse_batch_scrape_results(payload: Any, requested_urls: list[str]) -> list[FirecrawlDocumentSnapshot]:
    candidates = _extract_data_list(payload)
    snapshots: list[FirecrawlDocumentSnapshot] = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        snapshots.append(
            _snapshot_from_item(
                item,
                requested_urls[index] if index < len(requested_urls) else "",
            )
        )
    return snapshots


def _parse_scrape_result(payload: Any, requested_url: str) -> FirecrawlDocumentSnapshot | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    return _snapshot_from_item(data, requested_url)


def _extract_data_list(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("web", "results", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []
    if isinstance(data, list):
        return data
    return []


def _snapshot_from_item(item: dict[str, Any], requested_url: str) -> FirecrawlDocumentSnapshot:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source_url = str(
        item.get("url")
        or item.get("sourceURL")
        or metadata.get("sourceURL")
        or requested_url
    )
    final_url = str(
        item.get("finalUrl")
        or item.get("finalURL")
        or metadata.get("url")
        or metadata.get("sourceURL")
        or source_url
    )
    return FirecrawlDocumentSnapshot(
        source_url=source_url,
        final_url=final_url,
        title=_optional_text(item.get("title") or metadata.get("title")),
        markdown=_optional_text(item.get("markdown")),
        html=_optional_text(item.get("html")),
        metadata=dict(metadata),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
