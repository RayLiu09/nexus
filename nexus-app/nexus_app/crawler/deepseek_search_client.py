from __future__ import annotations

from urllib.parse import urljoin

import httpx

from nexus_app.config import get_settings
from nexus_app.crawler.websearch_custom_client import (
    WebSearchCustomError,
    WebSearchCustomItem,
    WebSearchCustomResponse,
)


class HttpDeepSeekSearchClient:
    def search(self, *, query: str, count: int, time_range: str) -> WebSearchCustomResponse:
        settings = get_settings()
        if not settings.api_key_deepseek:
            raise WebSearchCustomError("deepseek search client is not configured")
        start, end = time_range.split("..", 1)
        dated_query = f"{query} after:{start} before:{end}"
        if len(dated_query) > 128:
            raise WebSearchCustomError("deepseek_query_too_long")
        try:
            with httpx.Client(timeout=settings.crawler_websearch_custom_timeout_seconds) as client:
                response = client.post(
                    urljoin(settings.base_url_deepseek.rstrip("/") + "/", "v1/tools/search"),
                    headers={"Authorization": f"Bearer {settings.api_key_deepseek}"},
                    json={"query": dated_query, "count": count, "need_content": True},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = "provider_rate_limited" if status == 429 else f"provider_http_{status}"
            raise WebSearchCustomError(reason) from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise WebSearchCustomError("provider_error") from exc
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise WebSearchCustomError("provider_invalid_response")
        items: list[WebSearchCustomItem] = []
        for raw in data["results"]:
            if not isinstance(raw, dict):
                continue
            url = raw.get("url")
            content = raw.get("content")
            if not isinstance(url, str) or not isinstance(content, str) or not content.strip():
                continue
            items.append(WebSearchCustomItem(
                result_id=url,
                title=str(raw.get("title") or ""),
                url=url.strip(),
                content=content.strip(),
                content_source="content",
                metadata={
                    "RankScore": raw.get("rerank_score"),
                    "AuthInfoLevel": raw.get("authority"),
                    "SiteName": raw.get("site_name"),
                    "PublishTime": raw.get("date"),
                    "ContentFormats": "text",
                },
            ))
        return WebSearchCustomResponse(items, None, None, None)
