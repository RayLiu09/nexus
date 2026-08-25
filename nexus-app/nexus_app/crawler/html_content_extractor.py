"""Deterministic Firecrawl HTML main-content extraction.

Firecrawl HTML is expected to be scraped with ``onlyMainContent=true``, but the
pipeline still runs a local extractor so crawler assets do not depend on LLM
latency or model-specific JSON behavior.  Locators point to the parsed Markdown.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import trafilatura

PARSER_BACKEND = "trafilatura-html-main-content-v1"


class HtmlMainContentExtractionError(Exception):
    """Raised when crawler HTML cannot produce a usable Markdown document."""


@dataclass(frozen=True)
class HtmlMainContentExtractionResult:
    title: str
    markdown: str
    blocks: list[dict[str, Any]]
    sections: list[dict[str, Any]]
    retrieval_hints: dict[str, Any]
    removed_noise: list[str]
    quality: dict[str, Any]


def extract_html_main_content(
    *,
    html: str,
    source_url: str | None,
    title_hint: str | None,
    metadata_hint: dict[str, Any] | None = None,
) -> HtmlMainContentExtractionResult:
    if not html.strip():
        raise HtmlMainContentExtractionError("crawler HTML content is empty")

    metadata_hint = metadata_hint or {}
    extracted, extractor_metadata = _extract_markdown_with_trafilatura(html, source_url=source_url)
    extractor_backend = "trafilatura"
    quality_flags: list[str] = []
    if not extracted:
        extracted = _fallback_html_to_markdown(html)
        extractor_backend = "html_text_fallback"
        quality_flags.append("html_text_fallback_used")
    markdown = _normalize_markdown(extracted)
    markdown, repaired_tables = _repair_gfm_table_separators(markdown)
    if repaired_tables:
        quality_flags.append("gfm_table_separator_repaired")
    if not markdown:
        raise HtmlMainContentExtractionError("crawler HTML extractor produced empty markdown")
    markdown, promoted_headings = _promote_policy_headings(markdown)
    if promoted_headings:
        quality_flags.append("policy_heading_promoted")

    title = _pick_title(
        title_hint=title_hint,
        extractor_metadata=extractor_metadata,
        markdown=markdown,
    )
    markdown, title_inserted = _ensure_markdown_title(title, markdown)
    if title_inserted:
        quality_flags.append("synthetic_title_heading")

    blocks = build_markdown_blocks(
        markdown,
        source_url=source_url,
        representation="html",
        parser_backend=PARSER_BACKEND,
    )
    sections = build_markdown_sections(blocks)
    for section in sections:
        for block in blocks:
            if section["start_seq_no"] <= block["seq_no"] <= section["end_seq_no"]:
                block["section_id"] = section["section_id"]
                block["source_locator"]["section_id"] = section["section_id"]
        section.pop("start_seq_no", None)
        section.pop("end_seq_no", None)

    metrics = _quality_metrics(markdown=markdown, blocks=blocks)
    quality_flags.extend(metrics["quality_flags"])
    return HtmlMainContentExtractionResult(
        title=title,
        markdown=markdown,
        blocks=blocks,
        sections=sections,
        retrieval_hints=_retrieval_hints(
            title=title,
            markdown=markdown,
            source_url=source_url,
            metadata_hint=metadata_hint,
            extractor_metadata=extractor_metadata,
        ),
        removed_noise=[],
        quality={
            "main_content_confidence": _confidence(metrics, extractor_backend),
            "markdown_completeness": "complete" if len(markdown) >= 300 else "partial",
            "noise_removal_confidence": 0.86 if not metrics["boilerplate_term_hits"] else 0.62,
            "locator_quality": "markdown_range",
            "quality_flags": sorted(set(quality_flags)),
            "parser_backend": PARSER_BACKEND,
            "extractor": {
                "primary": "trafilatura",
                "backend_used": extractor_backend,
                "content_chars": len(markdown),
                "paragraph_count": metrics["paragraph_count"],
                "heading_count": metrics["heading_count"],
                "link_text_ratio": metrics["link_text_ratio"],
                "boilerplate_term_hits": metrics["boilerplate_term_hits"],
            },
        },
    )


def build_markdown_blocks(
    markdown: str,
    *,
    source_url: str | None,
    representation: str,
    parser_backend: str,
) -> list[dict[str, Any]]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", markdown) if part.strip()]
    blocks: list[dict[str, Any]] = []
    cursor = 0
    for part in parts:
        heading = _heading_match(part)
        if heading:
            block_type = "heading"
            heading_level = heading[0]
            text = heading[1]
            block_markdown = part
        else:
            block_type = _block_type(part)
            heading_level = None
            text = _plain_text(part)
            block_markdown = part
        start = markdown.find(block_markdown, cursor)
        if start < 0:
            start = markdown.find(text, cursor)
        if start < 0:
            start = cursor
        end = start + len(block_markdown)
        cursor = end
        block_id = f"web-block-{len(blocks) + 1:04d}"
        block: dict[str, Any] = {
            "block_id": block_id,
            "block_type": block_type,
            "seq_no": len(blocks) + 1,
            "text": text,
            "md_char_range": [start, end],
            "source_locator": {
                "locator_type": "markdown_range",
                "source_url": source_url,
                "raw_representation": representation,
                "md_char_range": [start, end],
                "block_id": block_id,
                "section_id": None,
            },
            "source_url": source_url,
            "dom_path": None,
            "dom_index": None,
            "section_id": None,
            "metadata": {
                "source": "firecrawl",
                "raw_representation": representation,
                "parser_backend": parser_backend,
                "locator_type": "markdown_range",
            },
        }
        if heading_level:
            block["heading_level"] = heading_level
        blocks.append(block)
    return blocks


def build_markdown_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not blocks:
        return []
    heading_blocks = [block for block in blocks if block.get("block_type") == "heading"]
    if not heading_blocks:
        first = blocks[0]
        last = blocks[-1]
        return [{
            "section_id": "sec-0001",
            "heading": "正文",
            "level": 1,
            "parent_section_id": None,
            "start_block_id": first["block_id"],
            "end_block_id": last["block_id"],
            "start_seq_no": first["seq_no"],
            "end_seq_no": last["seq_no"],
            "md_char_range": [first["md_char_range"][0], last["md_char_range"][1]],
            "summary": None,
            "keywords": [],
        }]

    sections: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for index, heading in enumerate(heading_blocks, start=1):
        next_heading = heading_blocks[index] if index < len(heading_blocks) else None
        end_seq_no = (next_heading["seq_no"] - 1) if next_heading else blocks[-1]["seq_no"]
        end_block = next(block for block in reversed(blocks) if block["seq_no"] <= end_seq_no)
        level = int(heading.get("heading_level") or 1)
        while stack and int(stack[-1]["level"]) >= level:
            stack.pop()
        parent_id = stack[-1]["section_id"] if stack else None
        section = {
            "section_id": f"sec-{len(sections) + 1:04d}",
            "heading": str(heading.get("text") or "正文")[:120],
            "level": level,
            "parent_section_id": parent_id,
            "start_block_id": heading["block_id"],
            "end_block_id": end_block["block_id"],
            "start_seq_no": heading["seq_no"],
            "end_seq_no": end_seq_no,
            "md_char_range": [heading["md_char_range"][0], end_block["md_char_range"][1]],
            "summary": None,
            "keywords": [],
        }
        sections.append(section)
        stack.append(section)
    return sections


def _extract_markdown_with_trafilatura(html: str, *, source_url: str | None) -> tuple[str, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    try:
        meta = trafilatura.extract_metadata(html, default_url=source_url)
        if meta is not None:
            metadata = {
                "title": getattr(meta, "title", None),
                "date": getattr(meta, "date", None),
                "author": getattr(meta, "author", None),
                "sitename": getattr(meta, "sitename", None),
                "hostname": getattr(meta, "hostname", None),
            }
    except Exception:
        metadata = {}

    for favor_precision in (True, False):
        extracted = trafilatura.extract(
            html,
            url=source_url,
            output_format="markdown",
            include_comments=False,
            include_links=False,
            include_images=False,
            include_tables=True,
            deduplicate=True,
            favor_precision=favor_precision,
        )
        if extracted and extracted.strip():
            metadata["favor_precision"] = favor_precision
            return extracted, metadata
    return "", metadata


class _TextHTMLParser(HTMLParser):
    _SKIP_TAGS = {"head", "title", "meta", "link", "script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[tuple[str, int | None, str]] = []
        self._skip_depth = 0
        self._current_type: str | None = None
        self._current_level: int | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._begin("heading", int(tag[1]))
        elif tag in {"p", "div", "article", "section"}:
            self._begin("paragraph", None)
        elif tag == "li":
            self._begin("list", None)
        elif tag == "br":
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "article", "section", "li"}:
            self._end()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _collapse(data)
        if text:
            self._buffer.append(text)

    def _begin(self, block_type: str, heading_level: int | None) -> None:
        if self._buffer:
            self._end()
        self._current_type = block_type
        self._current_level = heading_level
        self._buffer = []

    def _end(self) -> None:
        text = _collapse("".join(self._buffer))
        self._buffer = []
        if text and not _looks_like_noise(text):
            self.parts.append((self._current_type or "paragraph", self._current_level, text))
        self._current_type = None
        self._current_level = None

    def close(self) -> None:
        super().close()
        if self._buffer:
            self._end()


def _fallback_html_to_markdown(html: str) -> str:
    parser = _TextHTMLParser()
    parser.feed(html)
    parser.close()
    lines: list[str] = []
    for block_type, level, text in parser.parts:
        if block_type == "heading":
            lines.append(f"{'#' * (level or 2)} {text}")
        elif block_type == "list":
            lines.append(text if text.startswith(("- ", "* ")) else f"- {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def _normalize_markdown(markdown: str) -> str:
    lines: list[str] = []
    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.rstrip().replace("\xa0", " ").replace("\u3000", " ")
        if not _looks_like_noise(stripped):
            lines.append(stripped)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _repair_gfm_table_separators(markdown: str) -> tuple[str, int]:
    """Add missing GFM header separators emitted by some HTML extractors.

    Trafilatura occasionally emits a pipe-delimited HTML table as a header
    directly followed by data rows.  That is readable source text but invalid
    GFM, so `react-markdown` renders it as a paragraph.  Repair only adjacent
    table rows with equal column counts and leave valid tables and fenced code
    blocks untouched.
    """
    lines = markdown.split("\n")
    output: list[str] = []
    repaired = 0
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        output.append(line)
        if (
            not in_fence
            and (index == 0 or not _is_pipe_table_row(lines[index - 1]))
            and index + 1 < len(lines)
            and _is_pipe_table_row(line)
            and _is_pipe_table_row(lines[index + 1])
        ):
            header = _pipe_table_cells(line)
            next_row = _pipe_table_cells(lines[index + 1])
            if (
                len(header) >= 2
                and len(header) == len(next_row)
                and all(cell for cell in header)
                and not (
                    len(output) >= 2
                    and _is_gfm_separator_row(_pipe_table_cells(output[-2]))
                )
                and not _is_gfm_separator_row(header)
                and not _is_gfm_separator_row(next_row)
            ):
                output.append("| " + " | ".join("---" for _ in header) + " |")
                repaired += 1
        index += 1
    return "\n".join(output), repaired


def _is_pipe_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3


def _pipe_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def _is_gfm_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _pick_title(*, title_hint: str | None, extractor_metadata: dict[str, Any], markdown: str) -> str:
    hinted_title = str(title_hint or "").strip()
    extracted_title = str(extractor_metadata.get("title") or "").strip()
    # The crawler's retained title is source metadata.  Prefer it only when it
    # contains an explicit school identity that the extractor's generic page
    # title lost; this keeps institution-profile identity tied to a reliable
    # source field instead of a recommendation/footer block.
    if _contains_institution_name(hinted_title) and not _contains_institution_name(extracted_title):
        return _strip_site_suffix(hinted_title)[:256]
    candidates = [
        extracted_title,
        hinted_title,
    ]
    heading = re.search(r"^#\s+(.+)$", markdown, flags=re.MULTILINE)
    if heading:
        candidates.append(heading.group(1).strip())
    for value in candidates:
        if value:
            return _strip_site_suffix(value)[:256]
    first_line = next((line.strip("# ").strip() for line in markdown.splitlines() if line.strip()), "")
    return first_line[:120] or "未命名网页文档"


def _contains_institution_name(value: str) -> bool:
    return bool(re.search(
        r"[\u4e00-\u9fa5]{2,28}(?:职业技术大学|职业技术学院|职业学院|技师学院|技工学校|大学|学院|学校)",
        value,
    ))


def _strip_site_suffix(value: str) -> str:
    return re.split(
        r"\s*[-_—]\s*(中国教育和科研计算机网CERNET|中国教育和科研计算机网|CERNET|中华人民共和国.*|.*人民政府)$",
        value,
        maxsplit=1,
    )[0].strip() or value


def _ensure_markdown_title(title: str, markdown: str) -> tuple[str, bool]:
    if not title or re.search(r"^#\s+", markdown, flags=re.MULTILINE):
        return markdown, False
    return f"# {title}\n\n{markdown}" if markdown else f"# {title}", True


_POLICY_INLINE_HEADING_RE = re.compile(
    r"^("
    r"(?:[一二三四五六七八九十]+[、.．]|[（(][一二三四五六七八九十\d]+[）)])"
    r"[^。；;：:\n]{2,48}"
    r")(?=(?:一是|二是|三是|四是|五是|首先|其次|另外|再次|下一步|目前|截至|根据|按照|为|在|对|将))"
)


def _promote_policy_headings(markdown: str) -> tuple[str, list[str]]:
    """Split policy-style inline headings into Markdown heading blocks.

    Some government pages flatten section headings and the following paragraph
    into one text node, e.g. ``一、重点任务一是...``.  Splitting before block
    construction gives retrieval a stable section boundary without depending
    on the source DOM.
    """
    parts = [part.strip() for part in re.split(r"\n\s*\n", markdown) if part.strip()]
    out: list[str] = []
    promoted: list[str] = []
    for part in parts:
        match = _POLICY_INLINE_HEADING_RE.match(_plain_text(part))
        if match:
            heading = match.group(1).strip()
            rest = part[len(match.group(1)):].strip()
            if heading and rest:
                level = 3 if re.match(r"^[（(]", heading) else 2
                out.append(f"{'#' * level} {heading}")
                out.append(rest)
                promoted.append(heading)
                continue
        if _heading_match(part) or _block_type(part) in {"list", "table", "code"}:
            out.append(part)
            continue
        out.append(part)
    return "\n\n".join(out), promoted


def _heading_match(part: str) -> tuple[int, str] | None:
    stripped = part.strip()
    markdown_heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
    if markdown_heading:
        return len(markdown_heading.group(1)), markdown_heading.group(2).strip()
    candidate = _strip_markdown_emphasis(stripped)
    if len(candidate) <= 80 and re.match(r"^([一二三四五六七八九十]+[、.．]|第[一二三四五六七八九十\d]+[章节篇]|[（(][一二三四五六七八九十\d]+[）)])", candidate):
        return 2, candidate
    if len(candidate) <= 80 and stripped.startswith("**") and stripped.endswith("**"):
        return 2, candidate
    return None


def _block_type(part: str) -> str:
    stripped = part.lstrip()
    if stripped.startswith(("- ", "* ")) or re.match(r"^\d+[.)、]\s+", stripped):
        return "list"
    if re.search(r"\n?\|.+\|\n\|?[-:| ]+\|", part):
        return "table"
    if stripped.startswith("```"):
        return "code"
    return "paragraph"


def _plain_text(markdown: str) -> str:
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "", markdown)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`>#-]+", " ", text)
    return _collapse(text)


def _strip_markdown_emphasis(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"^(\*\*|__)\s*", "", stripped)
    stripped = re.sub(r"\s*(\*\*|__)$", "", stripped)
    return _collapse(stripped)


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ").replace("\u3000", " ")).strip()


def _quality_metrics(*, markdown: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    text_chars = len(re.sub(r"\s+", "", markdown))
    link_text_chars = sum(len(match.group(1)) for match in re.finditer(r"\[([^\]]+)]\([^)]+\)", markdown))
    flags: list[str] = []
    boilerplate_hits = [term for term in _NOISE_TERMS if term in markdown]
    if text_chars < 100:
        flags.append("main_content_too_short")
    if boilerplate_hits:
        flags.append("boilerplate_terms_detected")
    link_ratio = round(link_text_chars / max(text_chars, 1), 4)
    if link_ratio > 0.25:
        flags.append("link_text_ratio_high")
    return {
        "paragraph_count": sum(1 for block in blocks if block.get("block_type") == "paragraph"),
        "heading_count": sum(1 for block in blocks if block.get("block_type") == "heading"),
        "link_text_ratio": link_ratio,
        "boilerplate_term_hits": boilerplate_hits,
        "quality_flags": flags,
    }


def _confidence(metrics: dict[str, Any], extractor_backend: str) -> float:
    score = 0.88 if extractor_backend == "trafilatura" else 0.66
    if "main_content_too_short" in metrics["quality_flags"]:
        score -= 0.18
    if "link_text_ratio_high" in metrics["quality_flags"]:
        score -= 0.18
    if metrics["boilerplate_term_hits"]:
        score -= 0.12
    return max(0.0, min(1.0, round(score, 2)))


def _retrieval_hints(
    *,
    title: str,
    markdown: str,
    source_url: str | None,
    metadata_hint: dict[str, Any],
    extractor_metadata: dict[str, Any],
) -> dict[str, Any]:
    topics = [topic for topic in _TOPIC_TERMS if topic in f"{title}\n{markdown}"]
    publish_date = extractor_metadata.get("date") or _first_date(markdown)
    return {
        "primary_topics": topics[:8],
        "policy_subjects": [topic for topic in topics if topic in _POLICY_TERMS],
        "region": metadata_hint.get("region_code"),
        "issuing_org_candidates": _org_candidates(title, markdown),
        "time_range": {"publish_date": publish_date} if publish_date else {},
        "source_url": source_url,
        "template_code": metadata_hint.get("template_code"),
    }


def _org_candidates(title: str, markdown: str) -> list[str]:
    candidates: list[str] = []
    for text in (title, markdown[:1200]):
        for match in re.finditer(r"([\u4e00-\u9fff]{2,30}(部|厅|局|委|政府|办公室|委员会))", text):
            value = match.group(1)
            if value not in candidates:
                candidates.append(value)
            if len(candidates) >= 5:
                return candidates
    return candidates


def _first_date(markdown: str) -> str | None:
    match = re.search(r"(20\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})日?", markdown)
    if not match:
        return None
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _looks_like_noise(value: str) -> bool:
    text = value.strip()
    return bool(text) and any(term in text for term in _NOISE_TERMS)


_NOISE_TERMS = (
    "分享到",
    "扫一扫",
    "上一篇",
    "下一篇",
    "相关阅读",
    "相关链接",
    "友情链接",
    "打印本页",
    "关闭窗口",
    "网站地图",
    "版权所有",
    "Copyright",
    "特别声明",
)
_TOPIC_TERMS = (
    "职业教育",
    "产教融合",
    "电子商务",
    "跨境电商",
    "农村电商",
    "直播电商",
    "旅游电商",
    "数字经济",
    "区域经济",
    "数字教学资源",
)
_POLICY_TERMS = {"职业教育", "产教融合", "电子商务", "数字经济"}
