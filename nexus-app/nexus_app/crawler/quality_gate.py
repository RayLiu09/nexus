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


def evaluate_websearch_item(
    *,
    query: str,
    title: str,
    url: str,
    content: str,
    rank_score: Any,
    min_text_chars: int = 200,
    min_rank_score: float = 0.15,
) -> QualityDecision:
    """Apply deterministic pre-ingest quality checks to one Custom result."""
    try:
        validate_target_url(url, allow_http_authority_seed=True)
    except UnsafeCrawlerUrlError:
        return QualityDecision(False, "unsafe_url")

    parsed = urlparse(url)
    path = (parsed.path or "/").rstrip("/")
    normalized_title = title.strip().lower()
    if (
        not path
        or normalized_title in {"首页", "主页", "网站首页", "home", "index"}
        or _is_websearch_aggregation_path(path)
    ):
        return QualityDecision(False, "homepage_or_channel")
    if _is_websearch_news_item(path, title, content):
        return QualityDecision(False, "news_report")
    if len(content.strip()) < min_text_chars:
        return QualityDecision(False, "too_short")
    try:
        if float(rank_score) < min_rank_score:
            return QualityDecision(False, "low_relevance")
    except (TypeError, ValueError):
        return QualityDecision(False, "missing_rank_score")

    query_terms = _websearch_query_terms(query)
    haystack = f"{title}\n{content[:4000]}".lower()
    if query_terms and not any(term.lower() in haystack for term in query_terms):
        return QualityDecision(False, "topic_coverage_insufficient")
    return QualityDecision(True)


def _websearch_query_terms(query: str) -> list[str]:
    # The provider accepts one query string, which may still contain a compact
    # thematic expression such as "电子商务产业(跨境电商和直播电商)政策和市场概况".
    terms = [item.strip() for item in re.split(r"[()（）/、]+|和", query) if len(item.strip()) >= 2]
    expanded = list(terms)
    if any("电子商务" in item for item in terms):
        expanded.append("电商")
    return expanded or ([query.strip()] if query.strip() else [])


def _is_websearch_aggregation_path(path: str) -> bool:
    """Recognize search-result/page-navigation URLs, not article URLs."""
    lowered = unquote(path).lower()
    filename = lowered.rsplit("/", 1)[-1]
    if re.fullmatch(r"(?:page|index|list)[-_]?\d*\.html?", filename):
        return True
    return "/col/" in lowered and filename in {"", "index.html", "index.htm"}


def _is_websearch_news_item(path: str, title: str, content: str) -> bool:
    """Exclude news only when it lacks reusable policy/report/market evidence."""
    lowered_path = unquote(path).lower()
    is_news_route = any(marker in lowered_path for marker in ("/news/", "/m_gnxw/", "/instant/"))
    evidence_text = f"{title}\n{content[:2000]}"
    if is_news_route and _has_market_or_report_evidence(evidence_text):
        return False
    # URL rules are authoritative. These terms only cover common pages whose
    # CMS route does not disclose the news channel; policy/report titles still
    # take precedence so policy interpretation is not accidentally rejected.
    headline = f"{title}\n{content[:500]}"
    if is_news_route or any(marker in headline for marker in ("记者", "通讯员", "消息（记者", "新闻报道")):
        return not any(marker in title for marker in ("政策", "通知", "报告", "解读", "白皮书"))
    return False


def _has_market_or_report_evidence(text: str) -> bool:
    return any(marker in text for marker in (
        "市场", "产业", "规模", "增长", "统计", "数据", "同比", "环比", "进出口",
        "零售额", "运行情况", "监测", "分析", "指数", "报告", "白皮书", "政策",
    ))


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
