from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import httpx

from nexus_app.config import get_settings


class WebSearchCustomError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebSearchCustomItem:
    result_id: str
    title: str
    url: str
    content: str
    content_source: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class WebSearchCustomResponse:
    items: list[WebSearchCustomItem]
    request_id: str | None
    log_id: str | None
    time_cost_ms: int | None


class HttpWebSearchCustomClient:
    def search(self, *, query: str, count: int, time_range: str) -> WebSearchCustomResponse:
        settings = get_settings()
        if not settings.crawler_websearch_custom_api_key:
            raise WebSearchCustomError("websearch custom client is not configured")
        payload = {"Query": query, "SearchType": "web", "Count": count,
                   "Filter": {"NeedContent": True, "NeedUrl": True}, "TimeRange": time_range,
                   "Industry": "gov", "QueryControl": {"QueryRewrite": True}, "ContentFormats": "markdown"}
        try:
            with httpx.Client(timeout=settings.crawler_websearch_custom_timeout_seconds) as client:
                response = client.post(settings.crawler_websearch_custom_api_endpoint,
                    headers={"Authorization": f"Bearer {settings.crawler_websearch_custom_api_key}"}, json=payload)
                if response.status_code >= 400:
                    response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise WebSearchCustomError("provider_rate_limited" if exc.response.status_code == 429 else "provider_http_error") from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise WebSearchCustomError("provider_error") from exc
        meta = data.get("ResponseMetadata") or {}
        if meta.get("Error"):
            code = str(meta["Error"].get("Code") or meta["Error"].get("CodeN") or "")
            raise WebSearchCustomError("provider_rate_limited" if code == "700429" else f"provider_api_{code or 'error'}")
        result = data.get("Result") or {}; result = result.get("CustomSearchResp") or result
        items = []
        for raw in result.get("WebResults") or []:
            content = str(raw.get("Content") or raw.get("Summary") or "").strip()
            url = str(raw.get("Url") or "").strip()
            if content and url:
                items.append(WebSearchCustomItem(str(raw.get("Id") or ""), str(raw.get("Title") or ""), url, content,
                    "content" if raw.get("Content") else "summary", {k: raw.get(k) for k in ("SiteName", "PublishTime", "RankScore", "AuthInfoLevel", "AuthInfoDes", "ContentFormats")}))
        return WebSearchCustomResponse(items, meta.get("RequestId"), result.get("LogId"), result.get("TimeCost"))
