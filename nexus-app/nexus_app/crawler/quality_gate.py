from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

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


def domain_of(url: str) -> str | None:
    host = urlparse(url).hostname
    return host.lower() if host else None

