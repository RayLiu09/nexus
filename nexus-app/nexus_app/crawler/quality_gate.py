from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote, urlparse
from typing import Any

from nexus_app.crawler.firecrawl_client import FirecrawlDocumentSnapshot
from nexus_app.crawler.url_safety import UnsafeCrawlerUrlError, validate_target_url


_LOGIN_OR_CAPTCHA_PATTERNS = (
    re.compile(r"登录|登陆|验证码|captcha|sign\s*in|login", re.IGNORECASE),
)

_ACTIVITY_CONTENT_MARKERS = (
    "活动预告", "活动通知", "会议通知", "报名通知", "培训通知", "赛事通知",
    "讲座通知", "报名参加", "活动现场", "成功举办", "圆满举行", "开幕式",
    "闭幕式", "签约仪式", "领导调研", "参观考察",
)

_FORMAL_POLICY_MARKERS = (
    "实施意见", "实施方案", "管理办法", "暂行办法", "条例", "规划", "指南",
    "政策解读", "政策文件", "发文机关", "文号", "第一条", "第二条", "施行",
)

@dataclass(frozen=True)
class QualityDecision:
    accepted: bool
    reason: str | None = None


def evaluate_websearch_item(
    *,
    title: str,
    url: str,
    content: str,
    rank_score: Any,
    min_text_chars: int = 200,
    min_rank_score: float = 0.15,
) -> QualityDecision:
    """Clean WebSearch candidates without re-evaluating provider topic recall."""
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

    return QualityDecision(True)


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
        return not any(
            marker in title
            for marker in ("政策", "通知", "报告", "解读", "白皮书", "实施意见", "实施方案", "办法", "条例")
        )
    return False


def _has_market_or_report_evidence(text: str) -> bool:
    return any(marker in text for marker in (
        "市场", "产业", "规模", "增长", "统计", "数据", "同比", "环比", "进出口",
        "零售额", "运行情况", "监测", "分析", "指数", "报告", "白皮书", "政策",
    ))


def evaluate_snapshot(
    snapshot: FirecrawlDocumentSnapshot,
    *,
    min_text_chars: int = 80,
) -> QualityDecision:
    try:
        validate_target_url(snapshot.final_url, allow_http_authority_seed=True)
    except UnsafeCrawlerUrlError:
        return QualityDecision(False, "unsafe_url")

    if is_pdf_candidate(snapshot.final_url or snapshot.source_url, snapshot.metadata):
        return QualityDecision(True)

    text = snapshot.text_for_quality.strip()
    if len(text) < min_text_chars:
        return QualityDecision(False, "too_short")
    if any(pattern.search(text[:2000]) for pattern in _LOGIN_OR_CAPTCHA_PATTERNS):
        return QualityDecision(False, "login_or_captcha")

    if is_low_value_activity_content(snapshot.title or "", text):
        return QualityDecision(False, "low_value_activity")

    return QualityDecision(True)


def normalized_content_fingerprint(snapshot: FirecrawlDocumentSnapshot) -> str | None:
    """Fingerprint Firecrawl HTML/Markdown by readable body, not transport bytes."""
    if is_pdf_candidate(snapshot.final_url or snapshot.source_url, snapshot.metadata):
        return None
    body = snapshot.markdown or _html_to_text(snapshot.html or "")
    normalized = _normalize_readable_text(body)
    if not normalized:
        return None
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_low_value_activity_content(title: str, content: str) -> bool:
    """Reject activity-only news without suppressing reusable formal evidence."""
    evidence = f"{title}\n{content[:4000]}"
    if any(marker in evidence for marker in _FORMAL_POLICY_MARKERS):
        return False
    if _has_market_or_report_evidence(evidence):
        return False
    return any(marker in evidence for marker in _ACTIVITY_CONTENT_MARKERS)


def _html_to_text(value: str) -> str:
    without_non_content = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", value, flags=re.I | re.S)
    return re.sub(r"<[^>]+>", " ", without_non_content)


def _normalize_readable_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", normalized).strip()


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
