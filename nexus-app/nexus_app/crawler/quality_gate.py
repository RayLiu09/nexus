from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from nexus_app.crawler.firecrawl_client import FirecrawlDocumentSnapshot
from nexus_app.crawler.url_safety import UnsafeCrawlerUrlError, validate_target_url


_ACCESS_BLOCK_PATTERNS = (
    re.compile(r"(?:请|需|需要|必须|先)?(?:登录|登陆)(?:后)?(?:查看|访问|继续|才能|以继续|以查看)"),
    re.compile(r"(?:无权|没有权限|访问受限|权限不足)(?:访问|查看|阅读)?"),
    re.compile(r"(?:sign\s*in|log\s*in)\s+(?:to|for)\s+(?:view|access|continue)", re.IGNORECASE),
)

_AUTH_CHALLENGE_PATTERNS = (
    re.compile(r"(?:请输入|填写|输入).{0,12}(?:验证码|校验码)"),
    re.compile(r"(?:验证码|校验码).{0,16}(?:验证|登录|提交|刷新)"),
    re.compile(r"(?:人机|安全|身份)(?:验证|校验)"),
    re.compile(r"(?:captcha|recaptcha|hcaptcha|verify\s+you(?:r)?\s*(?:identity|human))", re.IGNORECASE),
    re.compile(r"(?:用户名|账号|账户).{0,30}(?:密码|password)|(?:密码|password).{0,30}(?:登录|login|sign\s*in)", re.IGNORECASE),
)

_ACTIVITY_CONTENT_MARKERS = (
    "活动预告", "活动通知", "会议通知", "报名通知", "培训通知", "赛事通知",
    "讲座通知", "报名参加", "活动现场", "成功举办", "圆满举行", "开幕式",
    "闭幕式", "签约仪式", "领导调研", "参观考察", "开班", "培训班",
    "联合主办", "参培学员", "结业后", "揭牌", "签约", "出席", "致辞",
    "共同见证",
)

_PERSON_PROFILE_TITLE_MARKERS = (
    "追梦人", "人物故事", "创业故事", "人物风采", "先进个人", "奋斗者", "榜样",
)

_PERSON_PROFILE_CONTENT_MARKERS = (
    "（完）", "(完)", "资料图", "记者", "通讯员",
)

_FORMAL_POLICY_MARKERS = (
    "实施意见", "实施方案", "管理办法", "暂行办法", "条例", "规划", "指南",
    "政策解读", "政策文件", "发文机关", "文号", "第一条", "第二条", "施行", "实施路径",
)

_GITHUB_BLOB_HOSTS = frozenset({"github.com", "www.github.com"})

_GITHUB_SESSION_SHELL_MARKERS = (
    "you signed in with another tab or window",
    "you signed out in another tab or window",
    "you switched accounts on another tab or window",
)

# GitHub source-file viewer line-count header, e.g. "54635 lines (54635 loc)".
# Rendered documentation (README/wiki) is not emitted through this viewer.
_GITHUB_LINE_COUNT_RE = re.compile(
    r"\b\d{1,7}\s+lines?\s*\(\s*\d{1,7}\s+loc\s*\)",
    re.IGNORECASE,
)

# CJK unified ideographs. Firecrawl web search can surface English-language
# brand/dictionary/encyclopedia pages that match a Chinese keyword only through
# its English translation (e.g. "nationaltoday.com", Merriam-Webster, Wikipedia).
# NEXUS pilot domains are Chinese-language documents, so a crawled body with no
# Han character is rejected as out-of-scope noise at admission.
_HAN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")

# Search-result pages often contain many genuine policy titles and issuers.
# They are navigation aggregates, not a single evidence-bearing document.
_SEARCH_NAVIGATION_TITLE_MARKERS = (
    "智能云搜索",
    "站内搜索",
    "搜索结果",
)
_SEARCH_RESULT_COUNT_RE = re.compile(
    r"(?:相关\s*)?结果\s*\d{1,7}\s*条",
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
    min_text_chars: int = 200,
) -> QualityDecision:
    """Validate result usability without re-evaluating provider relevance."""
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
    if _is_websearch_navigation_results_page(title, url, content):
        return QualityDecision(False, "navigation_search_results")
    if _is_websearch_news_item(path, title, content):
        return QualityDecision(False, "news_report")
    if len(content.strip()) < min_text_chars:
        return QualityDecision(False, "too_short")
    return QualityDecision(True)


def _is_websearch_aggregation_path(path: str) -> bool:
    """Recognize search-result/page-navigation URLs, not article URLs."""
    lowered = unquote(path).lower()
    filename = lowered.rsplit("/", 1)[-1]
    if re.fullmatch(r"(?:page|index|list)[-_]?\d*\.html?", filename):
        return True
    return "/col/" in lowered and filename in {"", "index.html", "index.htm"}


def _is_websearch_navigation_results_page(title: str, url: str, content: str) -> bool:
    """Recognize an actual search-result aggregation, not policy detail text.

    A search title alone is too broad, and a generic query parameter is not
    reliable across government portals.  Require the page's result-count
    topology as well as either an explicit search title or a search endpoint
    with an established query parameter.  This lets policy details that cite a
    search service or discuss a count continue through the normal gate.
    """
    parsed = urlparse(url)
    path = unquote(parsed.path or "/").rstrip("/").lower()
    query_keys = {key.lower() for key in parse_qs(parsed.query, keep_blank_values=True)}
    has_result_count = bool(_SEARCH_RESULT_COUNT_RE.search(content[:4000]))
    if not has_result_count:
        return False

    has_search_title = any(marker in title for marker in _SEARCH_NAVIGATION_TITLE_MARKERS)
    is_portal_search_endpoint = (
        (path == "/so" or path.startswith("/so/"))
        and bool({"qt", "sitecode", "tab"} & query_keys)
    )
    is_generic_search_endpoint = (
        (path == "/search" or path.startswith("/search/"))
        and bool({"q", "query", "keyword", "keywords"} & query_keys)
    )
    return has_search_title or is_portal_search_endpoint or is_generic_search_endpoint


def _is_websearch_news_item(path: str, title: str, content: str) -> bool:
    """Exclude news only when it lacks reusable policy/report/market evidence."""
    lowered_path = unquote(path).lower()
    is_news_route = any(marker in lowered_path for marker in ("/news/", "/m_gnxw/", "/instant/"))
    evidence_text = f"{title}\n{content[:2000]}"
    if is_news_route and (
        _has_market_or_report_evidence(evidence_text)
        or any(marker in evidence_text for marker in _FORMAL_POLICY_MARKERS)
    ):
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
    """Detect reusable report/statistical evidence, not a domain word alone.

    A single mention such as ``电子商务产业发展`` is common in activity
    recaps and curriculum descriptions. It is not evidence that a news page
    carries reusable market research or policy-report knowledge.
    """
    if re.search(r"\d+(?:\.\d+)?\s*[%％]", text):
        return True
    return any(marker in text for marker in (
        "市场规模", "统计数据", "统计口径", "数据来源", "数据表明", "数据显",
        "同比", "环比", "进出口", "零售额", "运行情况", "监测", "指数", "报告",
        "白皮书", "研究结论", "调研结果", "样本数据", "政策文件", "政策解读",
    ))


def evaluate_snapshot(
    snapshot: FirecrawlDocumentSnapshot,
    *,
    min_text_chars: int = 300,
) -> QualityDecision:
    try:
        validate_target_url(snapshot.final_url, allow_http_authority_seed=True)
    except UnsafeCrawlerUrlError:
        return QualityDecision(False, "unsafe_url")

    if is_pdf_candidate(snapshot.final_url or snapshot.source_url, snapshot.metadata):
        return QualityDecision(True)

    noise_reason = _github_blob_noise_reason(snapshot)
    if noise_reason is not None:
        return QualityDecision(False, noise_reason)

    text = snapshot.text_for_quality.strip()
    if _is_login_or_captcha_blocked(text):
        return QualityDecision(False, "login_or_captcha")
    if is_low_value_activity_content(snapshot.title or "", text):
        return QualityDecision(False, "low_value_activity")
    if is_low_value_person_profile(snapshot.title or "", text):
        return QualityDecision(False, "low_value_person_profile")
    if len(text) < min_text_chars:
        return QualityDecision(False, "too_short")
    if not _HAN_CHAR_RE.search(text):
        return QualityDecision(False, "non_chinese_content")

    return QualityDecision(True)


def _github_blob_noise_reason(snapshot: FirecrawlDocumentSnapshot) -> str | None:
    """Return a rejection reason for GitHub blob pages that are display shells.

    GitHub ``/{owner}/{repo}/blob/`` URLs can resolve to two kinds of noise that
    must never become knowledge assets: a session shell (JavaScript not
    rendered, leaving only the login/session notice) and a source-code file
    viewer (raw code rather than a rendered document).  Both are detected from
    the snapshot URL and body so they are rejected before any job is submitted.
    """
    url = snapshot.final_url or snapshot.source_url
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if not (
        parsed.hostname in _GITHUB_BLOB_HOSTS
        and len(path_parts) >= 4
        and path_parts[2] == "blob"
    ):
        return None

    text = (snapshot.markdown or _html_to_text(snapshot.html or "")).lower()

    matched_markers = [
        marker for marker in _GITHUB_SESSION_SHELL_MARKERS if marker in text
    ]
    if len(matched_markers) >= 2:
        return "github_blob_page_shell"

    if _GITHUB_LINE_COUNT_RE.search(text):
        return "github_blob_source_file"

    return None


def _is_login_or_captcha_blocked(text: str) -> bool:
    """Detect an access wall without treating site navigation as a login page.

    Firecrawl can retain global navigation even with ``onlyMainContent``.  A
    standalone "用户登录" link, or a ``login`` substring inside its URL, is not
    evidence that the fetched article itself requires authentication.
    """
    candidate = text[:2000]
    return any(pattern.search(candidate) for pattern in (
        *_ACCESS_BLOCK_PATTERNS,
        *_AUTH_CHALLENGE_PATTERNS,
    ))


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
    # One generic activity word is insufficient: it can occur in a substantive
    # policy or report. Multiple event markers identify event recaps without
    # consulting the originating search query or its topic.
    marker_hits = sum(marker in evidence for marker in _ACTIVITY_CONTENT_MARKERS)
    return marker_hits >= 2


def is_low_value_person_profile(title: str, content: str) -> bool:
    """Reject human-interest news that lacks reusable document evidence.

    The gate is intentionally narrow: a title must explicitly frame a person
    as an inspirational/profile story and the body must carry a news-story
    closing signal. This avoids using the crawler query or rejecting ordinary
    enterprise case studies solely because they mention a person.
    """
    evidence = f"{title}\n{content[:4000]}"
    if any(marker in evidence for marker in _FORMAL_POLICY_MARKERS):
        return False
    if _has_market_or_report_evidence(evidence):
        return False
    return (
        any(marker in title for marker in _PERSON_PROFILE_TITLE_MARKERS)
        and any(marker in evidence for marker in _PERSON_PROFILE_CONTENT_MARKERS)
    )


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
