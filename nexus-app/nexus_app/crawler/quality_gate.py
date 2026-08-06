from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse
from typing import Any

from nexus_app.crawler.firecrawl_client import FirecrawlDocumentSnapshot
from nexus_app.crawler.url_safety import UnsafeCrawlerUrlError, validate_target_url


_LOGIN_OR_CAPTCHA_PATTERNS = (
    re.compile(r"登录|登陆|验证码|captcha|sign\s*in|login", re.IGNORECASE),
)


@dataclass(frozen=True)
class QualityDecision:
    accepted: bool
    reason: str | None = None


def evaluate_snapshot(
    snapshot: FirecrawlDocumentSnapshot,
    *,
    topic_keywords: list[str],
    min_text_chars: int = 80,
) -> QualityDecision:
    try:
        validate_target_url(snapshot.final_url, allow_http_authority_seed=True)
    except UnsafeCrawlerUrlError:
        return QualityDecision(False, "unsafe_url")

    if is_pdf_candidate(snapshot.final_url or snapshot.source_url, snapshot.metadata):
        haystack = "\n".join(
            str(part)
            for part in [
                snapshot.title or "",
                snapshot.markdown or "",
                snapshot.metadata.get("search_description", ""),
                snapshot.final_url or snapshot.source_url,
            ]
            if part
        )
        keywords = [item.strip() for item in topic_keywords if item.strip()]
        if keywords and not any(keyword in haystack for keyword in keywords):
            return QualityDecision(False, "topic_mismatch")
        return QualityDecision(True)

    text = snapshot.text_for_quality.strip()
    if len(text) < min_text_chars:
        return QualityDecision(False, "too_short")
    if any(pattern.search(text[:2000]) for pattern in _LOGIN_OR_CAPTCHA_PATTERNS):
        return QualityDecision(False, "login_or_captcha")

    haystack = f"{snapshot.title or ''}\n{text[:4000]}"
    keywords = [item.strip() for item in topic_keywords if item.strip()]
    if keywords and not any(keyword in haystack for keyword in keywords):
        return QualityDecision(False, "topic_mismatch")

    return QualityDecision(True)


def is_pdf_candidate(url: str, metadata: dict[str, Any] | None = None) -> bool:
    parsed = urlparse(url)
    path = unquote(parsed.path or "").lower()
    query = unquote(parsed.query or "").lower()
    if path.endswith(".pdf") or ".pdf" in query:
        return True
    metadata = metadata or {}
    for key in (
        "content_type",
        "contentType",
        "mime_type",
        "mimeType",
        "file_type",
        "fileType",
        "format",
    ):
        value = str(metadata.get(key) or "").lower()
        if "application/pdf" in value or value == "pdf":
            return True
    return False


def domain_of(url: str) -> str | None:
    host = urlparse(url).hostname
    return host.lower() if host else None
