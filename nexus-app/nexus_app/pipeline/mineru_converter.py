"""MinerU v3 middle-json → normalized blocks + body_markdown.

Converts the raw parse artifact produced by MinerU into the normalized block
list and body_markdown string used by normalized_document.

MinerU v3 block structure
─────────────────────────
Flat blocks  (text / title / abstract / ref_text / interline_equation)
    top-level 'lines' → spans → {type, content}
    span types: text | inline_equation | interline_equation

Composite blocks  (image / chart / table)
    top-level 'blocks' → sub-blocks (*_body, *_caption)
    body span types:  image | chart | table  (carry image_path; table also has html)
    caption span type: text

Per-block markdown offset (Stage 2.2)
─────────────────────────────────────
Each block carries an OPTIONAL ``md_char_range = [start, end]`` field giving
its character span inside the returned body_markdown. The markdown text itself
is byte-identical to the value emitted before this index was added — index
data lives ONLY on the blocks list, never injected into the markdown stream.
Downstream LLM/RAGFlow inputs are therefore unaffected.

Public API
──────────
    convert(pdf_info, image_uris, image_analyzer, storage) → (blocks, body_markdown)
    assert_no_anchor_pollution(text) -> None
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ``pdf_renderer(page_idx) -> bytes`` returns a JPEG/PNG render of the PDF page
# at the given 0-based index. Used to rescue cross-page tables whose
# continuation pages produced no MinerU artifact at all. None to disable.
PdfPageRenderer = Callable[[int], bytes]

# ---------------------------------------------------------------------------
# Anchor-pollution guardrail
# ---------------------------------------------------------------------------
# md_char_range is out-of-band — markdown body MUST NOT carry block anchors.
# These patterns are forbidden in any text that flows to LLM/RAGFlow/render.
# See ARCHITECT.md "Chunk Locator Contract" / memory feedback_md_char_range_out_of_band.

_FORBIDDEN_ANCHOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<!--\s*block:", re.IGNORECASE),
    re.compile(r"\[#block-"),
    re.compile(r"\{\{\s*anchor"),
    # Zero-width characters that some tokenizers misread as content
    re.compile(r"[\u200B\u200C\u200D\uFEFF]"),
)

_ENV_ASSERT_FLAG = "NEXUS_ASSERT_NO_ANCHORS"


def assert_no_anchor_pollution(text: str) -> None:
    """Raise AssertionError if `text` contains any forbidden block-anchor marker.

    Runtime check intended for dev/staging only. Enabled when env
    ``NEXUS_ASSERT_NO_ANCHORS=1``; otherwise a no-op (production stays cheap).
    Production safety still rests on the byte-stability snapshot test.
    """
    if os.environ.get(_ENV_ASSERT_FLAG) != "1":
        return
    for pat in _FORBIDDEN_ANCHOR_PATTERNS:
        if pat.search(text):
            raise AssertionError(
                f"block anchor leaked into markdown stream (pattern={pat.pattern!r})"
            )

# ---------------------------------------------------------------------------
# Span-level text extraction
# ---------------------------------------------------------------------------

_PUNCT_NO_SPACE_BEFORE = frozenset(".,;:!?)]}\"'")


def _span_text(span: dict[str, Any]) -> str:
    stype = span.get("type", "")
    if stype == "text":
        return span.get("content", "")
    if stype == "inline_equation":
        latex = span.get("content", "")
        return f"${latex}$" if latex else ""
    if stype == "interline_equation":
        latex = span.get("content", "")
        return f"$${latex}$$" if latex else ""
    return ""


def _join_spans(spans: list[dict[str, Any]]) -> str:
    """Join spans in one PDF line with smart spacing around inline equations."""
    result = ""
    for span in spans:
        token = _span_text(span)
        if not token:
            continue
        if not result:
            result = token
            continue
        needs_space = True
        if result[-1] in (" ", "(", "[", "{"):
            needs_space = False
        elif span.get("type") != "inline_equation" and token[0] in _PUNCT_NO_SPACE_BEFORE:
            needs_space = False
        result = result + (" " if needs_space else "") + token
    return result


# ---------------------------------------------------------------------------
# Line-level joining with PDF hyphenation resolution
# ---------------------------------------------------------------------------

def _join_lines(line_texts: list[str]) -> str:
    """Join physical PDF lines, resolving end-of-line hyphenation.

    A trailing hyphen preceded by a letter is a line-break hyphen: remove it
    and concatenate directly.  All other lines are joined with a space.
    """
    if not line_texts:
        return ""
    result = line_texts[0]
    for line in line_texts[1:]:
        if not line:
            continue
        if result.endswith("-") and len(result) >= 2 and result[-2].isalpha():
            result = result[:-1] + line
        else:
            result = result + " " + line
    return result


# ---------------------------------------------------------------------------
# Block-level text helpers
# ---------------------------------------------------------------------------

def _flat_block_text(block: dict[str, Any]) -> str:
    """Text from a flat block (text/title/abstract/ref_text/interline_equation)."""
    line_texts = [
        _join_spans(line.get("spans", []))
        for line in block.get("lines", [])
    ]
    return _join_lines([t for t in line_texts if t])


def _composite_image_paths(block: dict[str, Any]) -> list[str]:
    """image_path values from *_body sub-blocks of a composite block."""
    paths: list[str] = []
    for sub in block.get("blocks", []):
        if sub.get("type", "").endswith("_body"):
            for line in sub.get("lines", []):
                for span in line.get("spans", []):
                    p = span.get("image_path")
                    if p:
                        paths.append(p)
    return paths


def _composite_caption(block: dict[str, Any]) -> str:
    """Caption text from *_caption sub-blocks, with hyphenation resolution."""
    line_texts: list[str] = []
    for sub in block.get("blocks", []):
        if sub.get("type", "").endswith("_caption"):
            for line in sub.get("lines", []):
                parts = [
                    s.get("content", "")
                    for s in line.get("spans", [])
                    if s.get("type") == "text"
                ]
                joined = "".join(parts)
                if joined:
                    line_texts.append(joined)
    return _join_lines(line_texts)


# Regex contracts (see docs/document_normalize_defects.md §9.3):
#   - MinerU pipeline tables always carry ``colspan`` / ``rowspan`` even when
#     the value is 1, so ``<tr>`` / ``<td>`` must accept arbitrary attributes.
#   - Both ``<td>`` and ``<th>`` are valid cell tags. MinerU currently emits
#     only ``<td>`` but other backends (HTML / future vlm) may emit ``<th>``.
#   - Cell content can contain inline ``<br>``, ``<eq>...</eq>`` (already
#     handled), and the four standard HTML entities.

_TABLE_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TABLE_CELL_RE = re.compile(
    r"<(?P<tag>t[dh])(?P<attrs>[^>]*)>(?P<inner>.*?)</(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)
_ATTR_INT_RE = re.compile(r'(?P<key>colspan|rowspan)\s*=\s*"?(?P<val>\d+)"?', re.IGNORECASE)


def _cell_attr_int(attrs: str, key: str) -> int:
    """Extract colspan / rowspan as int (default 1, never below 1)."""
    for m in _ATTR_INT_RE.finditer(attrs or ""):
        if m.group("key").lower() == key.lower():
            try:
                v = int(m.group("val"))
                return max(1, v)
            except ValueError:
                return 1
    return 1


def _normalise_cell_text(inner: str) -> str:
    """Flatten inline HTML inside a cell into single-line markdown-safe text.

    Strip-then-decode order matters: HTML tags are stripped BEFORE entity
    decoding so that ``&lt;x&gt;`` (a literal ``<x>`` the document author
    typed) is not destroyed by the tag stripper. Pipe / backslash inside
    cell text are escaped so they do not break the markdown table grammar.
    """
    text = re.sub(r"<\s*br\s*/?\s*>", " ", inner, flags=re.IGNORECASE)
    text = re.sub(r"</?\s*(p|div|span)\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)  # drop any other inline HTML tag
    # Now safe to decode entities — what's left of "<" or ">" must come from
    # &lt;/&gt; that the author typed.
    text = (
        text.replace("&nbsp;", " ")
            .replace("&quot;", '"')
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
    )
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    return text


def _table_html_to_markdown(html: str) -> str:
    """Convert MinerU HTML table to GitHub-Flavoured Markdown.

    Handles:
      - ``<tr>`` / ``<td>`` / ``<th>`` with arbitrary attributes (colspan,
        rowspan, class, style, …). MinerU emits ``colspan="1" rowspan="1"``
        on every cell — the prior regex missed all of them, dropping 99.6%
        of cell content (see docs/document_normalize_defects.md §9).
      - ``colspan > 1``: cell content is duplicated across the spanned
        columns (GFM does not support real merge); this keeps row width
        consistent and content searchable.
      - ``rowspan > 1``: the cell value is propagated downward into the
        same column on subsequent rows so the row width matches the
        column count and the value remains visible (no empty placeholder).
      - Inline ``<eq>``, ``<br>``, simple block-inline wrappers; HTML
        entities (``&amp; &lt; &gt; &quot;``).
      - Pipe / backslash escaping inside cells so they do not break GFM.
    """
    # Inline equations first — keep them outside the tag-stripping pass
    # since $...$ math must survive. Entity decoding happens per-cell to
    # protect literal <x> typed as &lt;x&gt;.
    html = re.sub(r"<eq>(.*?)</eq>", lambda m: f"${m.group(1).strip()}$", html, flags=re.DOTALL)

    rows_raw = _TABLE_TR_RE.findall(html)
    if not rows_raw:
        return ""

    # First pass: parse each row into a list of (text, colspan, rowspan).
    parsed_rows: list[list[tuple[str, int, int]]] = []
    for row_html in rows_raw:
        cells: list[tuple[str, int, int]] = []
        for m in _TABLE_CELL_RE.finditer(row_html):
            text = _normalise_cell_text(m.group("inner"))
            cs = _cell_attr_int(m.group("attrs"), "colspan")
            rs = _cell_attr_int(m.group("attrs"), "rowspan")
            cells.append((text, cs, rs))
        parsed_rows.append(cells)

    if all(not r for r in parsed_rows):
        return ""

    # Compute total column count: the maximum sum of colspan in any row.
    col_count = max((sum(c[1] for c in r) for r in parsed_rows), default=0)
    if col_count == 0:
        return ""

    # Second pass: lay cells onto a fixed-width grid, propagating rowspan
    # downward and expanding colspan rightward.
    grid: list[list[str]] = []
    # pending_rowspan[col] = (text, remaining_rows) — when remaining_rows>0
    # the next row's column ``col`` must be filled with ``text`` instead of
    # the next parsed cell. Decremented after each row.
    pending: list[tuple[str, int] | None] = [None] * col_count

    for cells in parsed_rows:
        row: list[str] = []
        cell_iter = iter(cells)
        col = 0
        while col < col_count:
            if pending[col] is not None:
                text, remaining = pending[col]
                row.append(text)
                remaining -= 1
                pending[col] = (text, remaining) if remaining > 0 else None
                col += 1
                continue
            try:
                text, cs, rs = next(cell_iter)
            except StopIteration:
                # Row defined fewer cells than the grid — pad with empties.
                row.append("")
                col += 1
                continue
            for _ in range(cs):
                if col >= col_count:
                    break
                row.append(text)
                if rs > 1:
                    pending[col] = (text, rs - 1)
                col += 1
        grid.append(row)

    md_lines: list[str] = []
    md_lines.append("| " + " | ".join(grid[0]) + " |")
    md_lines.append("| " + " | ".join("---" for _ in range(col_count)) + " |")
    for row in grid[1:]:
        md_lines.append("| " + " | ".join(row) + " |")
    return "\n".join(md_lines)


def _vlm_blockquote(content: str) -> str:
    """Wrap VLM content as a valid multi-line Markdown blockquote."""
    return "\n".join(f"> {line}" if line.strip() else ">" for line in content.splitlines())


# ---------------------------------------------------------------------------
# Main converter
# ---------------------------------------------------------------------------

_VISUAL_TYPES = frozenset({"image", "chart", "table"})
_HEADING_LEVEL_MAP: dict[int, int] = {1: 1, 2: 2}


# ---------------------------------------------------------------------------
# Decorative-image classifier (defect #4)
# ---------------------------------------------------------------------------
# Used to short-circuit the VLM call for visuals that have no informational
# value to downstream chunking / governance / search: QR codes, logos, page
# decorators, badge icons, etc. Generating a multi-paragraph English VLM
# description for these merely inflates body_markdown noise.
#
# The classifier is conservative — it intentionally errs on the side of
# *running* VLM when uncertain, because losing genuine figure descriptions
# would be a worse regression than the noise we are trying to remove.
#
# Rules (any single match → decorative):
#   1. Filename / path hints (``qr``/``logo``/``icon``/``barcode``/``decor``).
#   2. Very small bbox (max edge < _DECOR_TINY_PX) → icon / badge.
#   3. Near-square bbox + small (max edge < _DECOR_SMALL_PX) + no caption →
#      QR-code shape.
# Tables and captioned figures are never decorative.

_DECOR_FILENAME_RE = re.compile(
    r"(?:^|[/_\-])(?:qr(?:code)?|logo|icon|badge|barcode|decor|seal|stamp)"
    r"(?:[/_\-.]|$)",
    re.IGNORECASE,
)
_DECOR_TINY_PX = 100
_DECOR_SMALL_PX = 240
_DECOR_SQUARE_RATIO_MIN = 0.80
_DECOR_SQUARE_RATIO_MAX = 1.25


def _bbox_dimensions(bbox: list[Any]) -> tuple[float, float] | None:
    if not bbox or len(bbox) < 4:
        return None
    try:
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError):
        return None
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    if w <= 0 or h <= 0:
        return None
    return w, h


def _is_decorative_visual(
    btype: str,
    img_paths: list[str],
    bbox: list[Any],
    caption: str,
) -> tuple[bool, str | None]:
    """Return (is_decorative, reason). ``reason`` is None when not decorative.

    ``reason`` is included for logging / telemetry only — it is not persisted
    onto the block.
    """
    if btype == "table":
        return False, None
    if caption and caption.strip():
        return False, None
    for path in img_paths:
        if _DECOR_FILENAME_RE.search(path):
            return True, "filename_hint"
    dims = _bbox_dimensions(bbox)
    if dims is None:
        return False, None
    w, h = dims
    max_dim = max(w, h)
    if max_dim < _DECOR_TINY_PX:
        return True, "tiny_bbox"
    if max_dim < _DECOR_SMALL_PX:
        ratio = w / h
        if _DECOR_SQUARE_RATIO_MIN <= ratio <= _DECOR_SQUARE_RATIO_MAX:
            return True, "square_small_bbox"
    return False, None


# ---------------------------------------------------------------------------
# Noise filter — defect #1 in docs/document_normalize_defects.md
# ---------------------------------------------------------------------------
# Strips two classes of low-value content right after the raw conversion loop
# and BEFORE md_char_range computation, so the (blocks, md_parts) pair stays
# 1:1 and the offsets emitted by _annotate_md_ranges remain correct:
#
#   1. Promo / watermark text inserted by third-party report distributors
#      (e.g. "报告搜一搜 / 800000+份行业研究报告 / 长按识别关注公众号").
#   2. VLM blockquote descriptions of purely decorative images (QR codes,
#      logos, barcodes) — the description has no factual grounding in the
#      source document and inflates token usage downstream.
#
# Rule data is module-local for now; if the keyword list grows beyond ~50
# entries or needs per-tenant tuning, lift it to a config file and load via
# the same registry pattern as ingest_validate.json.

_NOISE_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"报告搜一搜"),
    re.compile(r"长按识别关注公众号"),
    re.compile(r"扫码关注"),
    re.compile(r"扫一扫"),
    re.compile(r"\d{4,}\+?\s*份(行业)?研究报告"),
    re.compile(r"行业研究报告\s*下载"),
    re.compile(r"^\s*关注公众号\s*$", re.MULTILINE),
)

# VLM-generated descriptions of decorative images all share a small set of
# fingerprints. Matching the raw markdown segment is enough because
# _vlm_blockquote() prefixes every line with ">".
# Each pattern MUST anchor the decorative noun to a blockquote-opening line
# ("> The image is a QR code …"). Without that anchor we risk stripping
# substantive chart descriptions that happen to mention "QR code" in passing.
_DECORATIVE_VLM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*>\s*The image is a QR code", re.MULTILINE),
    re.compile(r"^\s*>\s*This (image|figure) is a (QR code|barcode|logo)\b", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*>\s*A (QR code|barcode|logo)\b", re.MULTILINE | re.IGNORECASE),
    re.compile(
        r"^\s*>.*?\bQR code \(Quick Response Code\)",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"^\s*>\s*(Summary:\s*)?This is a branded QR code\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"^\s*>.*?\bbranded QR code\b.*?\b(no additional labels|no text|no technical content|central logo)\b",
        re.MULTILINE | re.IGNORECASE,
    ),
)


def _classify_noise(block: dict[str, Any], md_part: str) -> str | None:
    """Return a non-empty reason string when (block, md_part) is noise.

    None means "keep". Reasons are stable strings for log aggregation.
    """
    if not md_part:
        return None
    for pat in _NOISE_TEXT_PATTERNS:
        if pat.search(md_part):
            return "watermark_text"
    btype = block.get("block_type")
    if btype in {"image", "chart"}:
        for pat in _DECORATIVE_VLM_PATTERNS:
            if pat.search(md_part):
                return "decorative_image_vlm"
    return None


# ---------------------------------------------------------------------------
# TOC extraction — defect #2 in docs/document_normalize_defects.md
# ---------------------------------------------------------------------------
# Pulls table-of-contents entries out of `body_markdown` and serializes them
# into a structured ``payload.toc`` list so they:
#   - do not pollute chunk content (avoids "标题 + 页码"伪片段 dominating
#     retrieval recall),
#   - remain queryable separately for outline / navigation features.
#
# Detection is intentionally conservative: TOC is the ONLY part of a document
# where heading-like text consistently terminates with a page number. Three
# line shapes cover ~all real-world cases:
#
#   1. Dot leader        ``X.Y.Z Title .......... 12``
#   2. Numbered section  ``1.2.3 Title  12``
#   3. Chinese chapter   ``第一章  Title  12``
#
# We require a RUN of ≥3 consecutive matching paragraph/heading blocks before
# extracting — single coincidental matches in body text stay untouched.

# Order matters: structured prefixes (chapter / numbered) match before the
# generic dot-leader, which would otherwise swallow the prefix into "title".
_TOC_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Chinese chapter / section: "第一章 Title  ......... 12"
    re.compile(
        r"^\s*(?P<num>第[一二三四五六七八九十百千]+[章节篇])\s+"
        r"(?P<title>.+?)\s*[\.\u2026]*\s*(?P<page>\d{1,4})\s*$"
    ),
    # Numbered (dotted) section: "1.2.3 Title  .......... 12"
    re.compile(
        r"^\s*(?P<num>\d+(?:\.\d+){0,4})\s+(?P<title>.+?)\s*[\.\u2026]*\s*(?P<page>\d{1,4})\s*$"
    ),
    # Generic dot leader without numbering prefix: "Title .......... 12"
    re.compile(
        r"^\s*(?P<title>.+?)\s*[\.\u2026]{3,}\s*(?P<page>\d{1,4})\s*$"
    ),
)

_TOC_MIN_RUN_LEN = 3
_TOC_ELIGIBLE_BLOCK_TYPES = frozenset({"paragraph", "heading"})


def _classify_toc_line(md_part: str) -> dict[str, Any] | None:
    """Return a structured entry if md_part looks like a TOC line, else None.

    Levels are derived from the numbering depth (``1`` → 1, ``1.2.3`` → 3);
    dot-leader lines default to level 1 because they carry no number; Chinese
    chapter markers map to ``章`` → 1, ``节`` → 2, ``篇`` → 1.
    """
    if not md_part:
        return None
    text = md_part.strip()
    # Strip leading markdown heading hashes so "# 第一章 X 5" still matches.
    text = re.sub(r"^#+\s+", "", text)
    for pat in _TOC_PATTERNS:
        m = pat.match(text)
        if not m:
            continue
        title = m.group("title").strip()
        page = int(m.group("page"))
        num = m.groupdict().get("num") or ""
        if num and num[0].isdigit():
            level = num.count(".") + 1
        elif num:
            level = 2 if num.endswith("节") else 1
        else:
            level = 1
        entry: dict[str, Any] = {
            "level": level,
            "title": title,
            "page": page,
        }
        if num:
            entry["number"] = num
        return entry
    return None


# A block whose text matches at least this many distinct TOC entries
# (across line splits OR within a single concatenated line) is treated as a
# "concatenated TOC block" — MinerU sometimes flattens the entire TOC into a
# single paragraph block (sample 4abe6b71… p7 wrapped the full TOC under one
# block-p07-023 paragraph).
_TOC_CONCAT_MIN_HITS = 4
# Catches dotted numbers / Chinese chapters / dot-leader fragments embedded
# inside a single concatenated TOC paragraph. Greedier than the per-line
# patterns above because we are matching substrings, not whole lines.
_TOC_INLINE_RE = re.compile(
    r"(?:"
    r"第[一二三四五六七八九十百千]+[章节篇]\s*\S*?\s*[.\u2026]{2,}\s*-?\s*\d+\s*-?"
    r"|\d+(?:\.\d+){0,4}\s*\S*?\s*[.\u2026]{2,}\s*-?\s*\d+\s*-?"
    r"|\S+?\s*[.\u2026]{3,}\s*-?\s*\d+\s*-?"
    r")",
    re.UNICODE,
)


def _classify_toc_concat_block(md_part: str) -> list[dict[str, Any]] | None:
    """Detect a single block whose text contains many TOC fragments
    (numbered or dot-leader). Returns parsed entries, or None when the block
    doesn't look like a concatenated TOC.
    """
    if not md_part or len(md_part) < 40:
        return None
    fragments = _TOC_INLINE_RE.findall(md_part)
    if len(fragments) < _TOC_CONCAT_MIN_HITS:
        return None
    entries: list[dict[str, Any]] = []
    for frag in fragments:
        entry = _classify_toc_line(frag.strip())
        if entry is None:
            # Try once more after stripping trailing "- N -" markers some
            # PDFs add around page numbers.
            cleaned = re.sub(r"\s*-\s*(\d+)\s*-?\s*$", r" \1", frag.strip())
            entry = _classify_toc_line(cleaned)
        if entry is not None:
            entries.append(entry)
    return entries if len(entries) >= _TOC_CONCAT_MIN_HITS else None


def _extract_toc(
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Find TOC runs / concatenated TOC blocks, return
    ``(toc, blocks_without_toc, md_parts_without_toc)``.

    Two detection modes (either triggers extraction):

      1. **Run mode** (original): ≥ ``_TOC_MIN_RUN_LEN`` consecutive
         paragraph/heading blocks each matching one of ``_TOC_PATTERNS``.

      2. **Concatenated block mode** (added for sample 4abe6b71… p7 where
         MinerU collapsed the entire TOC into one paragraph): a single
         eligible block whose text contains ≥ ``_TOC_CONCAT_MIN_HITS``
         distinct dot-leader / numbered-section / chapter fragments.

    All blocks identified by either mode are extracted as TOC entries and
    removed from the markdown stream. Isolated matches outside runs and
    short blocks below the concat threshold are kept (false-positive
    suppression — body text occasionally ends with a number).
    """
    if len(blocks) != len(md_parts):
        logger.error(
            "_extract_toc: blocks/md_parts length mismatch; skipping TOC pass"
        )
        return [], blocks, md_parts

    # Per-block precomputed match (None when ineligible).
    matches: list[dict[str, Any] | None] = []
    # Per-block concat detection (None when not a concat-TOC block).
    concat_hits: list[list[dict[str, Any]] | None] = []
    for b, part in zip(blocks, md_parts):
        if b.get("block_type") not in _TOC_ELIGIBLE_BLOCK_TYPES:
            matches.append(None)
            concat_hits.append(None)
            continue
        matches.append(_classify_toc_line(part))
        concat_hits.append(_classify_toc_concat_block(part))

    # Mode 1: runs of consecutive matches.
    in_toc_idx: set[int] = set()
    run_start: int | None = None
    for i, entry in enumerate(matches):
        if entry is not None:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start >= _TOC_MIN_RUN_LEN:
                in_toc_idx.update(range(run_start, i))
            run_start = None
    if run_start is not None and len(matches) - run_start >= _TOC_MIN_RUN_LEN:
        in_toc_idx.update(range(run_start, len(matches)))

    # Mode 2: concat blocks (any block where concat_hits[i] is not None).
    concat_idx_to_entries: dict[int, list[dict[str, Any]]] = {
        i: ent for i, ent in enumerate(concat_hits) if ent
    }

    if not in_toc_idx and not concat_idx_to_entries:
        return [], blocks, md_parts

    toc: list[dict[str, Any]] = []
    kept_blocks: list[dict[str, Any]] = []
    kept_parts: list[str] = []
    for i, (b, part) in enumerate(zip(blocks, md_parts)):
        if i in concat_idx_to_entries:
            for ent in concat_idx_to_entries[i]:
                ent["block_id"] = b.get("block_id")
                toc.append(ent)
            continue
        if i in in_toc_idx:
            entry = matches[i] or {}
            entry["block_id"] = b.get("block_id")
            toc.append(entry)
            continue
        kept_blocks.append(b)
        kept_parts.append(part)

    logger.info(
        "mineru_converter: extracted %d TOC entr%s",
        len(toc), "y" if len(toc) == 1 else "ies",
    )
    return toc, kept_blocks, kept_parts


# ---------------------------------------------------------------------------
# Cross-page table merge + empty-table cleanup
# (defect #3 in docs/document_normalize_defects.md)
# ---------------------------------------------------------------------------
# MinerU emits one ``block_type=table`` per physical page, even for tables
# that span multiple pages. Continuation pages typically lose their caption
# and frequently lose both image and HTML — leaving phantom "empty" table
# blocks that pollute blocks[] (and waste an md_char_range slot).
#
# This pass:
#   (a) collapses consecutive ``table`` blocks that look like the same
#       logical table (anchor has caption; continuations have neither
#       caption nor wildly different x-extent and sit on the next page);
#   (b) drops blocks where caption + image_uris + content are all empty;
#   (c) strips empty pipe-only rows ("|  |", "| | | |", ...) from the
#       remaining table markdown — those are MinerU artifacts that contain
#       no information and bloat chunk content.
#
# bbox merge: union of the anchor's bbox with each continuation's bbox.
# image_uris merge: dict-update preserves first occurrence of each filename.
# Pages: an additional ``page_range = [first, last]`` is recorded when more
#        than one physical page was merged.
# parse_quality = "image_only" is stamped when the merged block carries an
#        image but no textual content — downstream chunkers can treat such
#        tables differently.

_TABLE_BBOX_TOLERANCE_PX = 20

# Lines like "|  |" or "| | | |" or "|     |" — purely structural rows
# emitted by MinerU when a table cell is empty. Removing them is safe because
# the original byte stream offered no information either.
_EMPTY_TABLE_ROW_RE = re.compile(r"^\s*\|(?:\s*\|)+\s*$")


# Structural meta-labels VLMs add when describing charts / figures.
# Even when the prompt explicitly forbids them, models love to wrap content
# in "Chart Type: …", "Axis Labels:", "Legend Entries:", "Key Data Values:",
# closing "Trend:" / "Summary:" paragraphs etc. These add no information to
# the transcribed values themselves and pollute chunk content downstream.
#
# A line is dropped when it is JUST one of these labels (with optional
# bullet / bold markers) OR when it starts with the label followed by
# explanatory prose (no useful data). When a line starts with a label but
# also contains substantive content (e.g. axes statement built by the new
# chart prompt), the label-prefix is stripped but the value remains.

_VISUAL_META_LABELS = (
    "chart type",
    "axes",
    "axis labels",
    "axis label",
    "x-axis",
    "y-axis",
    "left y-axis",
    "right y-axis",
    "legend",
    "legend entries",
    "key data",
    "key data values",
    "key data values / trends",
    "key trends",
    "trend",
    "trends",
    "summary",
    "overall",
    "note",
    "interpretation",
    "observation",
    "observations",
    "key observations",
    "data points",
)

# Markers a model uses to introduce a meta-label line. Captures things like
# "- **Chart Type**:", "* Trend:", "Trend：", "Y-axis (left):", optional
# parenthetical qualifiers after the label, optional bold markers, etc.
_VISUAL_META_LINE_RE = re.compile(
    r"^\s*[-*•\d.)\s]*\**\s*("
    + "|".join(re.escape(label) for label in _VISUAL_META_LABELS)
    + r")\**\s*(?:\([^)]*\))?\s*[:：]",
    re.IGNORECASE,
)

# Lines that are PURE label (no value after the colon) — always dropped.
_VISUAL_META_LINE_PURE_RE = re.compile(
    r"^\s*[-*•\d.)\s]*\**\s*("
    + "|".join(re.escape(label) for label in _VISUAL_META_LABELS)
    + r")\**\s*(?:\([^)]*\))?\s*[:：]?\s*$",
    re.IGNORECASE,
)

# Chatty prologues. Drop the entire leading line when it matches.
_VISUAL_CHATTY_PREFIX_RE = re.compile(
    r"^\s*(当然可以|以下是|这是一(?:个|张|幅)|好的[，。!]?\s*以下|"
    r"sure[,!]?\s*here|here\s+is|of\s+course|certainly|"
    r"i\s+can|i\s+(?:will|'ll)\s+describe|let\s+me\s+describe)"
    r"[\s\S]*?[:：。.]\s*$",
    re.IGNORECASE,
)


def _sanitise_vlm_visual_response(text: str | None) -> str:
    """Strip VLM meta-labels & chatty prose from a chart/image description.

    Used for ``block_type in {"image", "chart"}`` responses. The §11 chart
    prompt asks the model NOT to emit "Chart Type:" / "Axis Labels:" /
    "Legend:" / "Key Data:" / "Trend:" / "Summary:" framing, but models
    drift back to it. This sanitiser is the safety net:

      - Drop leading chatty preambles ("Sure! Here is…", "当然可以…").
      - Drop lines that are JUST a structural meta-label
        (e.g. "Axis Labels:" alone, "Key Data Values / Trends:").
      - For lines that START with a meta-label followed by content (e.g.
        "X-axis: Years 2019–2024."), keep the trailing content and drop
        the label prefix so the substantive value survives.
      - Collapse runs of blank lines.

    Returns empty string only when nothing substantive remains; callers
    treat that as "sanitiser would erase everything, keep original".
    """
    if not text:
        return ""
    raw = text.strip()
    if raw == "-":
        return "-"
    lines = raw.splitlines()
    out: list[str] = []
    # 1. Drop a leading chatty prologue line if present.
    if lines and _VISUAL_CHATTY_PREFIX_RE.match(lines[0]):
        lines = lines[1:]
    # 2. Process remaining lines.
    for ln in lines:
        if _VISUAL_META_LINE_PURE_RE.match(ln):
            # Pure meta-label with no value → drop entirely.
            continue
        m = _VISUAL_META_LINE_RE.match(ln)
        if m:
            # Strip the label + colon, keep the trailing content.
            stripped_value = ln[m.end():].lstrip()
            if not stripped_value:
                continue
            # Preserve list bullets when the original had one so the line
            # still reads as part of a list.
            bullet_match = re.match(r"^\s*([-*•])\s+", ln)
            prefix = bullet_match.group(0) if bullet_match else ""
            out.append(f"{prefix}{stripped_value}")
            continue
        out.append(ln)
    # 3. Collapse multiple blank lines.
    collapsed: list[str] = []
    blank = False
    for ln in out:
        if not ln.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        collapsed.append(ln)
    cleaned = "\n".join(collapsed).strip()
    return cleaned


_TABULAR_HINT_RE = re.compile(
    r"\b(tabular(?:\s+comparison)?|matrix|grid)\b|"
    r"rows?\s*[:：]|columns?\s*[:：]",
    re.IGNORECASE,
)


def _looks_tabular(text: str | None) -> bool:
    """Return True when a chart-style VLM response strongly suggests the
    underlying image is actually a table that was mis-classified as a chart.

    Signals (any single match is enough — false positives just trigger an
    extra LLM call, false negatives let the noisy chart description leak):
      - Explicit "Tabular comparison" / "matrix" / "grid" in the description.
      - Both "Rows:" and "Columns:" axis labels (charts have X/Y axes, not
        rows/columns).
      - ≥3 actual GFM pipe rows present in the response (the model
        spontaneously emitted a markdown table inside the chart description).
    """
    if not text:
        return False
    if _TABULAR_HINT_RE.search(text) and re.search(r"\brows?\b", text, re.IGNORECASE):
        return True
    pipe_rows = sum(
        1 for ln in text.splitlines()
        if ln.strip().startswith("|") and ln.strip().endswith("|")
    )
    return pipe_rows >= 3


def _is_padding_row(line: str) -> bool:
    """A "padding row" is a pipe row where only 1 cell carries content and
    the rest are blank — a tell-tale sign the VLM stuffed prose (heading,
    paragraph, footnote, page number) into the table grid to keep emitting
    rows after the real table ended (sample 4abe6b71… p55 — see §10).

    Header rows (``| col1 | col2 | col3 |`` with all cells filled) and
    GFM separator rows (``| --- | --- |``) are NEVER padding. A 2-column
    table with one empty cell could be a real partial row, so we only
    flag tables with ≥ 3 columns and exactly 1 non-empty cell.
    """
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return False
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) < 3:
        return False
    # Separator rows ``--- :--- ---:`` are structural.
    if all(set(c) <= {"-", ":", " "} for c in cells if c):
        return False
    non_empty = [c for c in cells if c]
    return len(non_empty) == 1


def _sanitise_vlm_table_response(text: str | None) -> str:
    """Extract just the markdown-table portion from a chatty VLM response.

    LLMs reliably append/prepend prose even when the prompt forbids it
    (e.g. "当然可以。以下是…", "说明：表格共 N 列…", "若需导出为
    CSV/Markdown/Excel…"). This sanitiser is the safety net contracted
    in docs/document_normalize_defects.md §9.5(B) and §10:

      - Locate the first and last lines matching ``^\\s*\\|.*\\|\\s*$``.
      - Keep ONLY pipe-bordered lines between them (table rows or GFM
        separator rows). Discard everything before, after, or in between
        that does not match.
      - Drop "padding rows" (single non-empty cell out of ≥3) which
        are typically prose mis-packed into the table grid by the VLM
        when its rendered image extended past the real table boundary.
      - Return empty string when no qualifying lines are found — the
        caller treats that as "rescue failed" and keeps the existing
        MinerU content.

    The sentinel ``"-"`` (model's "image is empty" response per our
    prompt) is preserved verbatim.
    """
    if not text:
        return ""
    stripped = text.strip()
    if stripped == "-":
        return "-"
    lines = text.splitlines()
    pipe_indices = [
        i for i, ln in enumerate(lines)
        if ln.strip().startswith("|") and ln.strip().endswith("|")
    ]
    if not pipe_indices:
        return ""
    first, last = pipe_indices[0], pipe_indices[-1]
    kept: list[str] = []
    for i in range(first, last + 1):
        ln = lines[i].strip()
        if not (ln.startswith("|") and ln.endswith("|")):
            continue
        if _is_padding_row(ln):
            continue
        kept.append(ln)
    return "\n".join(kept)


def _strip_empty_table_rows(table_md: str) -> str:
    """Drop pipe-only rows from a markdown table snippet."""
    if not table_md or "|" not in table_md:
        return table_md
    kept: list[str] = []
    for line in table_md.splitlines():
        if _EMPTY_TABLE_ROW_RE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _table_md_is_useful(table_md: str | None) -> bool:
    """Return True when the markdown carries at least ~2 cells of real data.

    Used as the VLM-rescue trigger: MinerU pipeline mode sometimes emits an
    HTML table with a header and 25 empty body rows (one such anchor was
    observed on the 政策一览表 sample). We treat such output as "absent" so a
    cropped-image VLM call can recover the actual cell contents instead.

    Heuristic: count pipe rows with at least one non-empty cell. ≥ 2 is the
    minimum to call something a real table (header + ≥1 data row).
    """
    if not table_md:
        return False
    rows_with_content = 0
    for line in table_md.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # Markdown header separator row "|---|---|" — skip
        if all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        if any(c for c in cells):
            rows_with_content += 1
            if rows_with_content >= 2:
                return True
    return False


def _table_md_part(block: dict[str, Any]) -> str:
    """Re-render the markdown segment of a table block from its fields."""
    sections: list[str] = []
    caption = block.get("caption")
    if caption:
        sections.append(f"**{caption}**")
    content = block.get("content")
    if content:
        sections.append(content)
    return "\n\n".join(sections)


def _is_continuation_table(anchor: dict[str, Any], cand: dict[str, Any], last_page: int) -> bool:
    """Heuristic: is `cand` a continuation of `anchor` on the next page?"""
    if cand.get("block_type") != "table":
        return False
    if cand.get("caption"):
        return False
    if cand.get("page") != last_page + 1:
        return False
    abbox = anchor.get("bbox") or []
    cbbox = cand.get("bbox") or []
    if len(abbox) < 4 or len(cbbox) < 4:
        return False
    if abs(abbox[0] - cbbox[0]) > _TABLE_BBOX_TOLERANCE_PX:
        return False
    if abs(abbox[2] - cbbox[2]) > _TABLE_BBOX_TOLERANCE_PX:
        return False
    return True


def _rescue_multipage_tables_via_pdf(
    blocks: list[dict[str, Any]],
    md_parts: list[str],
    pdf_renderer: "PdfPageRenderer | None",
    image_analyzer: Any | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """For merged cross-page tables, render EACH page in ``page_range`` and
    ask the VLM to extract its slice as markdown, then concatenate the
    slices under a single header row.

    This is mandatory whenever the merged table spans >1 page: MinerU's
    cropped image (when present) only covers the anchor page; the merged
    block typically already carries the anchor's MinerU markdown for the
    first page. So this pass:

      - PRESERVES the anchor's existing ``content`` (the MinerU-parsed
        markdown for the first page — ground truth after the §9 P0 regex
        fix). That avoids spending an LLM call on a page MinerU already
        parsed correctly, and avoids replacing accurate cells with VLM
        approximations.
      - For each CONTINUATION page (``page_range[0]+1 .. page_range[-1]``),
        renders the underlying PDF page and calls VLM. The per-page result
        is concatenated below the anchor's rows; the header row from the
        first continuation is dropped to avoid duplication.

    No-op when:
      - pdf_renderer or image_analyzer is missing (test harnesses);
      - the table only spans a single page (anchor crop is sufficient);
      - the anchor has NO existing content AND every per-page VLM call
        fails (the original block is left unchanged in that case).
    """
    if pdf_renderer is None or image_analyzer is None:
        return blocks, md_parts
    if len(blocks) != len(md_parts):
        logger.error(
            "_rescue_multipage_tables_via_pdf: blocks/md_parts length mismatch; skip"
        )
        return blocks, md_parts

    rescued = 0
    for i, block in enumerate(blocks):
        if block.get("block_type") != "table":
            continue
        page_range = block.get("page_range")
        if not page_range or len(page_range) < 2:
            continue
        first, last = page_range[0], page_range[-1]
        if first is None or last is None or last <= first:
            continue
        caption = block.get("caption") or ""

        # Anchor's existing MinerU markdown is ground truth — keep it as
        # the first slice (no LLM call for the page MinerU already
        # parsed). When the anchor has no content we fall back to
        # rendering page `first` too.
        anchor_md = block.get("content") or ""
        anchor_md = _strip_empty_table_rows(anchor_md).strip()
        per_page_md: list[str] = []
        if anchor_md and _table_md_is_useful(anchor_md):
            per_page_md.append(anchor_md)
            cont_start = first + 1
        else:
            cont_start = first

        page_bboxes = block.get("per_page_bboxes") or {}
        for page_idx in range(cont_start, last + 1):
            # Crop the rendered page to the table bbox MinerU recorded for
            # this specific page (when available). Without cropping, VLM
            # mis-packs surrounding headings / paragraphs / footnotes into
            # the table — visible as duplicated section text on sample
            # 4abe6b71… p55 (see docs §10).
            bbox_for_page = page_bboxes.get(page_idx) if isinstance(page_bboxes, dict) else None
            try:
                # Renderer ignores the bbox kwarg when it does not support
                # it (test harnesses), so this stays backwards-compatible.
                try:
                    jpeg = pdf_renderer(page_idx, bbox=bbox_for_page)
                except TypeError:
                    jpeg = pdf_renderer(page_idx)
            except Exception as exc:
                logger.warning(
                    "_rescue_multipage_tables_via_pdf: render page %d failed: %s",
                    page_idx, exc,
                )
                continue
            if not jpeg:
                continue
            try:
                vlm_md = image_analyzer.analyze(jpeg, "table", caption)
            except Exception as exc:
                logger.warning(
                    "_rescue_multipage_tables_via_pdf: VLM page %d failed: %s",
                    page_idx, exc,
                )
                continue
            if not vlm_md:
                continue
            sanitised = _sanitise_vlm_table_response(vlm_md)
            cleaned = _strip_empty_table_rows(sanitised).strip()
            if cleaned and cleaned != "-" and _table_md_is_useful(cleaned):
                per_page_md.append(cleaned)
        # Only update when we either kept the anchor or rescued at least
        # one continuation. If neither happened the block stays as-is.
        if len(per_page_md) < (1 if anchor_md else 1):
            continue
        if not per_page_md:
            continue
        # When anchor was preserved AND continuation slices were added,
        # mark the merge as a partial rescue so downstream telemetry can
        # tell "anchor + LLM continuations" apart from "anchor only".
        merged = _concat_table_md_keep_first_header(per_page_md)
        block["content"] = merged
        if anchor_md and len(per_page_md) > 1:
            block["parse_quality"] = "vlm_rescue_continuations"
        else:
            block["parse_quality"] = "vlm_rescue_pages"
        md_parts[i] = _table_md_part(block)
        rescued += 1

    if rescued:
        logger.info(
            "mineru_converter: rescued %d cross-page table(s) via PDF rasterisation",
            rescued,
        )
    return blocks, md_parts


def _concat_table_md_keep_first_header(pages_md: list[str]) -> str:
    """Concatenate markdown tables from multiple page renders.

    The VLM returns a self-contained ``|header|...|---|...|data...|`` for
    every page. To produce a single coherent table we keep the first page's
    output as-is and, for subsequent pages, skip their leading header +
    separator rows so we don't repeat column titles every page.
    """
    if not pages_md:
        return ""
    if len(pages_md) == 1:
        return pages_md[0]
    out: list[str] = [pages_md[0]]
    for md in pages_md[1:]:
        lines = md.splitlines()
        # Drop leading non-pipe noise, the first header pipe row, and the
        # separator pipe row that follows it.
        idx = 0
        # Skip leading blanks / non-pipe lines
        while idx < len(lines) and not lines[idx].strip().startswith("|"):
            idx += 1
        # Skip header row
        if idx < len(lines):
            idx += 1
        # Skip separator row if present
        if idx < len(lines) and lines[idx].strip().startswith("|"):
            cells = [c.strip() for c in lines[idx].strip().strip("|").split("|")]
            if cells and all(set(c) <= {"-", ":"} for c in cells if c):
                idx += 1
        tail = "\n".join(lines[idx:]).strip()
        if tail:
            out.append(tail)
    return "\n".join(out)


def _merge_cross_page_tables(
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collapse cross-page table runs and drop empty table placeholders."""
    if len(blocks) != len(md_parts):
        logger.error(
            "_merge_cross_page_tables: blocks/md_parts length mismatch; skipping"
        )
        return blocks, md_parts

    out_blocks: list[dict[str, Any]] = []
    out_parts: list[str] = []
    dropped_empty = 0
    merged_runs = 0
    n = len(blocks)
    i = 0
    while i < n:
        block = blocks[i]
        # (b) Drop fully-empty table blocks (no anchor, no continuation).
        if (
            block.get("block_type") == "table"
            and not block.get("caption")
            and not block.get("image_uris")
            and not block.get("content")
        ):
            dropped_empty += 1
            i += 1
            continue

        # (a) Anchor table with caption: scan for continuations on next pages.
        if (
            block.get("block_type") == "table"
            and block.get("caption")
        ):
            merged = dict(block)
            merged["image_uris"] = dict(block.get("image_uris") or {})
            merged["bbox"] = list(block.get("bbox") or [])
            content_parts: list[str] = []
            first_content = merged.get("content")
            if first_content:
                content_parts.append(first_content)
            pages_in_run = [block.get("page")]
            # Per-page bboxes are kept so the multi-page PDF rescue can crop
            # each rendered page to the table region (see
            # docs/document_normalize_defects.md §10 — VLM otherwise greedily
            # packs neighbouring headings / paragraphs / footnotes into table
            # rows when the page has content below the table).
            per_page_bboxes: dict[int, list[float]] = {}
            anchor_page = block.get("page")
            if anchor_page is not None and len(merged["bbox"]) >= 4:
                per_page_bboxes[anchor_page] = list(merged["bbox"])
            last_page = block.get("page", -1)
            j = i + 1
            while j < n and _is_continuation_table(merged, blocks[j], last_page):
                cont = blocks[j]
                merged["image_uris"].update(cont.get("image_uris") or {})
                cbbox = cont.get("bbox") or []
                if len(cbbox) >= 4 and len(merged["bbox"]) >= 4:
                    merged["bbox"][3] = max(merged["bbox"][3], cbbox[3])
                if cont.get("content"):
                    content_parts.append(cont["content"])
                last_page = cont.get("page", last_page)
                pages_in_run.append(cont.get("page"))
                if cont.get("page") is not None and len(cbbox) >= 4:
                    per_page_bboxes[cont.get("page")] = list(cbbox)
                j += 1

            if j > i + 1:
                merged_runs += 1
                if len(pages_in_run) > 1:
                    merged["page_range"] = [pages_in_run[0], pages_in_run[-1]]
                if per_page_bboxes:
                    merged["per_page_bboxes"] = per_page_bboxes

            # (c) Clean up empty rows in merged content.
            joined = "\n".join(content_parts)
            joined = _strip_empty_table_rows(joined).strip()
            if joined:
                merged["content"] = joined
            else:
                merged.pop("content", None)

            if not merged.get("content") and merged.get("image_uris"):
                merged["parse_quality"] = "image_only"

            out_blocks.append(merged)
            out_parts.append(_table_md_part(merged))
            i = j
            continue

        # (c) Solitary table block with content but no anchor merge — still
        # benefit from empty-row cleanup.
        if block.get("block_type") == "table" and block.get("content"):
            cleaned = _strip_empty_table_rows(block["content"]).strip()
            if cleaned != block["content"]:
                new_block = dict(block)
                if cleaned:
                    new_block["content"] = cleaned
                else:
                    new_block.pop("content", None)
                    if new_block.get("image_uris"):
                        new_block["parse_quality"] = "image_only"
                out_blocks.append(new_block)
                out_parts.append(_table_md_part(new_block))
                i += 1
                continue

        # Pass-through for all other blocks.
        out_blocks.append(block)
        out_parts.append(md_parts[i])
        i += 1

    if dropped_empty or merged_runs:
        logger.info(
            "mineru_converter: tables — merged %d run(s), dropped %d empty placeholder(s)",
            merged_runs, dropped_empty,
        )
    return out_blocks, out_parts


def _strip_noise(
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop (block, md_part) pairs flagged by _classify_noise in lockstep.

    Pairs are removed together so the strict 1:1 contract demanded by
    _annotate_md_ranges holds. Empty visual-block placeholders (block kept,
    md_part="") are never noise candidates here — defect #3 handles them.
    """
    if len(blocks) != len(md_parts):
        logger.error(
            "_strip_noise: blocks/md_parts length mismatch "
            "(blocks=%d, md_parts=%d); skipping noise filter",
            len(blocks), len(md_parts),
        )
        return blocks, md_parts

    kept_blocks: list[dict[str, Any]] = []
    kept_parts: list[str] = []
    dropped: list[tuple[str, str]] = []
    for block, part in zip(blocks, md_parts):
        reason = _classify_noise(block, part)
        if reason is None:
            kept_blocks.append(block)
            kept_parts.append(part)
            continue
        dropped.append((block.get("block_id", "?"), reason))

    if dropped:
        sample = dropped[:5]
        logger.info(
            "mineru_converter: stripped %d noise block(s); sample=%s",
            len(dropped), sample,
        )
    return kept_blocks, kept_parts


def convert(
    pdf_info: list[dict[str, Any]],
    image_uris: dict[str, str],
    image_analyzer: Any | None,
    storage: Any | None,
    pdf_renderer: PdfPageRenderer | None = None,
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Convert MinerU v3 pdf_info into (normalized_blocks, body_markdown, toc).

    Args:
        pdf_info:       MinerU parse_result['pdf_info'] — list of page dicts.
        image_uris:     Mapping of MinerU image filename → stored S3 URI.
        image_analyzer: Optional VLM analyzer for image/chart blocks.
        storage:        Object storage client used to fetch image bytes for VLM.
        pdf_renderer:   Optional PDF page rasteriser ``(page_idx) -> bytes``.
                        When provided alongside ``image_analyzer``, cross-page
                        ``image_only`` tables get their content recovered by
                        rendering each underlying page and calling VLM.

    Returns:
        blocks:         List of normalized block dicts.
        body_markdown:  Full document markdown string.
        toc:            List of ``{level, title, page, ...}`` entries extracted
                        from detected TOC runs; ``[]`` when the document has
                        no recognisable TOC (defect #2).
    """
    blocks: list[dict[str, Any]] = []
    md_parts: list[str] = []
    seq = 0

    for page in pdf_info:
        page_idx = page.get("page_idx", 0)
        for raw_block in page.get("para_blocks", []):
            seq += 1
            btype = raw_block.get("type", "text")
            bbox = raw_block.get("bbox", [])
            block_id = f"block-p{page_idx:02d}-{seq:03d}"
            source_locator = {"page": page_idx, "bbox": bbox}

            if btype in _VISUAL_TYPES:
                blocks, md_parts = _handle_visual(
                    raw_block, btype, block_id, seq, page_idx, bbox, source_locator,
                    image_uris, image_analyzer, storage, blocks, md_parts,
                )

            elif btype == "interline_equation":
                blocks, md_parts = _handle_equation(
                    raw_block, block_id, seq, page_idx, bbox, source_locator,
                    blocks, md_parts,
                )

            elif btype == "title":
                blocks, md_parts = _handle_title(
                    raw_block, block_id, seq, page_idx, bbox, source_locator,
                    blocks, md_parts,
                )

            else:
                blocks, md_parts = _handle_paragraph(
                    raw_block, block_id, seq, page_idx, bbox, source_locator,
                    blocks, md_parts,
                )

    # Defect #1: strip watermark/promo text + decorative-image VLM blockquotes
    # before computing offsets, so md_char_range references the cleaned stream.
    blocks, md_parts = _strip_noise(blocks, md_parts)

    # Defect #2: extract TOC runs into payload.toc and remove them from the
    # markdown stream. Runs through the same 1:1 contract so md_char_range on
    # the surviving blocks remains consistent.
    toc, blocks, md_parts = _extract_toc(blocks, md_parts)

    # Defect #3: merge cross-page tables, drop empty table placeholders, and
    # strip MinerU's "|  |" pipe-only empty rows that would otherwise become
    # noisy chunks.
    blocks, md_parts = _merge_cross_page_tables(blocks, md_parts)

    # Defect #3 extension: for every merged multi-page table, rasterise each
    # underlying PDF page and let VLM extract its slice. The anchor crop (if
    # present) only covers page 1 so single-page rescue cannot recover
    # continuation rows; we always override with the per-page concatenation
    # when a pdf_renderer + image_analyzer are wired.
    blocks, md_parts = _rescue_multipage_tables_via_pdf(
        blocks, md_parts, pdf_renderer, image_analyzer,
    )

    body_markdown = "\n\n".join(md_parts)
    _annotate_md_ranges(blocks, md_parts)
    # body_markdown is what reaches RAGFlow upload / LLM Prompt builders.
    # Anchor-pollution guard is opt-in via env (dev/staging); see module docstring.
    assert_no_anchor_pollution(body_markdown)
    return blocks, body_markdown, toc


# ---------------------------------------------------------------------------
# md_char_range computation (out-of-band; never mutates body_markdown)
# ---------------------------------------------------------------------------

_MD_SEPARATOR = "\n\n"


def _annotate_md_ranges(
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> None:
    """Attach ``md_char_range`` to each block based on ``\\n\\n``-joined offsets.

    Contract (see ARCHITECT.md "Chunk Locator Contract"):
      - ``md_char_range = [start, end]`` such that
        ``body_markdown[start:end] == md_parts[i]`` for each populated block.
      - Empty md_parts entry → ``md_char_range = None``. Block existed in the
        normalized list (e.g. a visual block with no caption/table/VLM text)
        but has zero footprint in the markdown stream; reverse-lookup will
        never resolve to it, which is the intended behaviour.
      - Strict 1:1 ordering between blocks[] and md_parts[] is required by the
        convert() loop (every handler that appends to blocks also appends to
        md_parts and vice versa). If they desync, this function bails out
        early without setting md_char_range to avoid emitting wrong offsets.
    """
    if len(blocks) != len(md_parts):
        logger.error(
            "mineru_converter: blocks/md_parts length mismatch "
            "(blocks=%d, md_parts=%d); skipping md_char_range",
            len(blocks), len(md_parts),
        )
        return

    cursor = 0
    sep_len = len(_MD_SEPARATOR)
    last_idx = len(md_parts) - 1
    for i, (block, part) in enumerate(zip(blocks, md_parts)):
        if part:
            block["md_char_range"] = [cursor, cursor + len(part)]
            cursor += len(part)
        else:
            block["md_char_range"] = None
        # join inserts a separator between every adjacent pair — including
        # around an empty entry — so advance the cursor for every gap.
        if i != last_idx:
            cursor += sep_len


# ---------------------------------------------------------------------------
# Per-block-type handlers
# ---------------------------------------------------------------------------

def _handle_visual(
    raw_block: dict[str, Any],
    btype: str,
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    image_uris: dict[str, str],
    image_analyzer: Any | None,
    storage: Any | None,
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    img_paths = _composite_image_paths(raw_block)
    caption = _composite_caption(raw_block)
    resolved_uris = {p: image_uris.get(p, "") for p in img_paths}

    # Tables: prefer MinerU HTML, then fall back to VLM when HTML is missing
    # or degraded (defect #3 extension — pipeline mode sometimes emits a
    # header row + 25 empty pipe rows for cross-page tables; that's a False
    # signal of "we extracted the table").
    table_md: str | None = None
    if btype == "table":
        for sub in raw_block.get("blocks", []):
            if sub.get("type") == "table_body":
                for line in sub.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("type") == "table" and span.get("html"):
                            table_md = _table_html_to_markdown(span["html"])
        if table_md:
            table_md = _strip_empty_table_rows(table_md).strip() or None

    # Decide whether VLM needs to run for this block:
    #   - image / chart  → always (subject to decorative gate)
    #   - table          → only when MinerU HTML was missing OR degraded
    needs_vlm = (
        image_analyzer is not None
        and img_paths
        and (btype != "table" or not _table_md_is_useful(table_md))
    )

    vlm_content: str | None = None
    decorative_reason: str | None = None
    table_rescued = False
    chart_to_table = False
    if needs_vlm:
        # Defect #4: differentiate VLM calls — skip decorative images
        # (QR / logo / icon / barcode) at the source instead of letting them
        # produce multi-paragraph blockquotes that need stripping later.
        # Tables are never considered decorative.
        is_decor, decorative_reason = _is_decorative_visual(btype, img_paths, bbox, caption)
        if is_decor:
            logger.info(
                "mineru_converter: skipped VLM for decorative %s %s (reason=%s)",
                btype, img_paths[0], decorative_reason,
            )
        else:
            primary_uri = image_uris.get(img_paths[0], "")
            if primary_uri and storage is not None:
                try:
                    key = primary_uri.split("/", 3)[-1] if primary_uri.startswith("s3://") else primary_uri
                    vlm_content = image_analyzer.analyze(storage.get_bytes(key), btype, caption)
                except Exception as exc:
                    logger.warning("VLM analysis failed for %s: %s", img_paths[0], exc)
        # For tables, promote VLM output to table_md when it's the better
        # source (HTML was absent / useless). Keep the existing MinerU output
        # only if VLM failed, returned the "-" sentinel, or returned chatty
        # prose without a real markdown table block.
        if btype == "table" and vlm_content:
            sanitised = _sanitise_vlm_table_response(vlm_content)
            cleaned_vlm = _strip_empty_table_rows(sanitised).strip()
            if cleaned_vlm and cleaned_vlm != "-" and _table_md_is_useful(cleaned_vlm):
                # Replace degraded HTML; track the rescue for quality telemetry.
                table_md = cleaned_vlm
                table_rescued = True
                vlm_content = None
                logger.info(
                    "mineru_converter: VLM rescued degraded table %s (cap=%r)",
                    block_id, (caption or "")[:50],
                )
            else:
                logger.info(
                    "mineru_converter: VLM produced no usable table for %s; "
                    "leaving block as image_only", block_id,
                )
                vlm_content = None

        # §11-C: chart→table re-route. When MinerU misclassified a table
        # as a "chart" block (e.g. sample p73-215 治理阶段对照表), the chart
        # prompt produces a meta-labelled description starting with
        # "Chart Type: Tabular comparison …" that is itself the noise the
        # user complained about. Detect that signal and re-call the model
        # with the table prompt; if it returns a useful markdown table,
        # promote the block to type="table" and track it.
        if (
            btype == "chart"
            and vlm_content
            and image_analyzer is not None
            and img_paths
            and storage is not None
            and _looks_tabular(vlm_content)
        ):
            primary_uri = image_uris.get(img_paths[0], "")
            if primary_uri:
                try:
                    key = primary_uri.split("/", 3)[-1] if primary_uri.startswith("s3://") else primary_uri
                    table_retry = image_analyzer.analyze(storage.get_bytes(key), "table", caption)
                except Exception as exc:
                    logger.warning(
                        "mineru_converter: chart→table retry failed for %s: %s",
                        img_paths[0], exc,
                    )
                    table_retry = None
                if table_retry:
                    cleaned_retry = _strip_empty_table_rows(
                        _sanitise_vlm_table_response(table_retry)
                    ).strip()
                    if (
                        cleaned_retry
                        and cleaned_retry != "-"
                        and _table_md_is_useful(cleaned_retry)
                    ):
                        btype = "table"
                        table_md = cleaned_retry
                        chart_to_table = True
                        vlm_content = None
                        logger.info(
                            "mineru_converter: chart→table recovered %s (cap=%r)",
                            block_id, (caption or "")[:50],
                        )

        # §11-B: for image/chart blocks, strip meta-labels & chatty prose
        # the model added despite §11-A's strict prompt. Only applied when
        # there is content to clean; on edge cases where the sanitiser
        # would erase everything we keep the original (better to show
        # noisy content than nothing at all).
        if btype in {"image", "chart"} and vlm_content:
            cleaned_vlm = _sanitise_vlm_visual_response(vlm_content)
            if cleaned_vlm:
                vlm_content = cleaned_vlm

    block: dict[str, Any] = {
        "block_id": block_id,
        "block_type": btype,
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "caption": caption,
        "image_uris": resolved_uris,
        "source_locator": source_locator,
    }
    if decorative_reason is not None:
        block["decorative"] = True
        block["parse_quality"] = "decorative"
    if table_rescued:
        block["parse_quality"] = "vlm_rescue"
    if chart_to_table:
        block["parse_quality"] = "chart_to_table_recovered"
    if table_md:
        block["content"] = table_md
    elif vlm_content:
        block["content"] = vlm_content
    blocks.append(block)

    md_section: list[str] = []
    if caption:
        md_section.append(f"**{caption}**")
    if table_md:
        md_section.append(table_md)
    elif vlm_content:
        md_section.append(_vlm_blockquote(vlm_content))
    md_parts.append("\n\n".join(md_section))

    return blocks, md_parts


def _handle_equation(
    raw_block: dict[str, Any],
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    latex_parts = [
        span["content"]
        for line in raw_block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("type") == "interline_equation" and span.get("content")
    ]
    latex = " ".join(latex_parts)
    if not latex:
        return blocks, md_parts

    blocks.append({
        "block_id": block_id,
        "block_type": "equation",
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "text": latex,
        "source_locator": source_locator,
    })
    md_parts.append(f"$$\n{latex}\n$$")
    return blocks, md_parts


def _handle_title(
    raw_block: dict[str, Any],
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    text = _flat_block_text(raw_block)
    if not text:
        return blocks, md_parts

    level = raw_block.get("level")
    md_level = _HEADING_LEVEL_MAP.get(level, 2) if level is not None else 2
    blocks.append({
        "block_id": block_id,
        "block_type": "heading",
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "text": text,
        "heading_level": md_level,
        "source_locator": source_locator,
    })
    md_parts.append(f"{'#' * md_level} {text}")
    return blocks, md_parts


def _handle_paragraph(
    raw_block: dict[str, Any],
    block_id: str,
    seq: int,
    page_idx: int,
    bbox: list[Any],
    source_locator: dict[str, Any],
    blocks: list[dict[str, Any]],
    md_parts: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    text = _flat_block_text(raw_block)
    if not text:
        return blocks, md_parts

    blocks.append({
        "block_id": block_id,
        "block_type": "paragraph",
        "seq_no": seq,
        "page": page_idx,
        "bbox": bbox,
        "text": text,
        "source_locator": source_locator,
    })
    md_parts.append(text)
    return blocks, md_parts
