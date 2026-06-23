"""Semantic repack — turn versioning blocks into retrieval-grade semantic units.

Owns slice 2 of ``docs/rag_semantic_chunks_implementation_plan.md``.

Pipeline
--------

::

   blocks
     │
     ▼
   drop_navigational   ── strip headings + document_metadata-tagged blocks
     │                    (headings stay around only as heading_path context)
     ▼
   drop_meaningless    ── pure page numbers / pure punctuation / orphan tokens
     │                    / decorative blocks (per-user explicit requirement)
     ▼
   attach_attribution  ── fold "数据来源: …" / "图 X-Y" short captions into the
     │                    adjacent chart / image / table they describe
     ▼
   merge_continuation  ── stitch the tail of a paragraph that overflows to the
     │                    next page back onto its parent
     ▼
   decompose_atomic_tables
     │                 ── split only row-record tables into overview +
     │                    table_row units; leave matrix/key-value/layout
     │                    tables intact
     ▼
   enrich_context      ── attach heading_path (h1→h3 chain) + caption +
     │                    anchor_role to each surviving unit
     ▼
   list[SemanticUnit]

A ``SemanticUnit`` is a plain dict (see :func:`_unit` for the contract) that
:meth:`nexus_app.knowledge.router.route_and_chunk` converts into a
``KnowledgeChunk`` with ``chunk_type=SEMANTIC_BLOCK`` and a full locator
(md_char_range, md_spans, heading_path, anchor_role).

Boundary contracts
------------------

- ``body_markdown`` is **never** mutated. ``md_char_range`` is the sole way to
  refer back into the body (per ``feedback_md_char_range_out_of_band``).
- ``role=document_metadata`` blocks (stamped by slice 1) are dropped here so
  title / authors / publish_date do **not** leak into chunks. Their text is
  already on ``normalized_ref.document_metadata``.
- heading blocks themselves are dropped from candidate chunks but kept in a
  separate stream as ``heading_path`` context for downstream chunks.

Thresholds are inlined for v1 (rules-only, no AI) and intentionally
conservative — false negatives (keep noise) are cheaper than false positives
(silently drop a real paragraph). Adjustable in v2 via
``config/semantic_repack.json`` per §八 of the plan.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type & constants
# ---------------------------------------------------------------------------

# Block types that may become chunk candidates. ``heading`` and ``equation``
# are excluded from candidacy but headings still feed into heading_path.
_CHUNKABLE_TYPES: frozenset[str] = frozenset({
    "paragraph", "table", "image", "chart", "list", "code", "equation",
})

# Heading marker for navigation drop; matches blocks emitted by mineru_converter
# (block_type="heading", heading_level=1..6) plus the legacy paragraph-starting-
# with-# convention.
_HEADING_TYPES: frozenset[str] = frozenset({"heading", "title"})

_MEDIA_TYPES: frozenset[str] = frozenset({"chart", "image", "table"})

# attach_attribution recognises these prefixes as the trigger for "fold this
# tiny paragraph into the adjacent media block". Tuned for Chinese gov / white-
# paper conventions; English equivalents included for the rare bilingual paper.
_ATTRIBUTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(数据来源|资料来源|来源)\s*[:：]"),
    re.compile(r"^\s*(注[：:]|注\d*[：:])"),
    re.compile(r"^\s*图\s*\d+([\-－.]\d+)*[\s:：]"),
    re.compile(r"^\s*表\s*\d+([\-－.]\d+)*[\s:：]"),
    re.compile(r"^\s*(Figure|Fig\.?|Table|Source)\s*[:：]?\s*\d", re.IGNORECASE),
)
_ATTRIBUTION_MAX_LEN = 120

# drop_meaningless rules. Each branch is intentionally tight: when in doubt
# we keep the block (better noisy chunk than vanished content).
_PURE_DIGITS_RE = re.compile(r"^\s*\d{1,4}\s*$")
_PURE_PUNCT_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
_PAGE_FOOTER_RE = re.compile(
    r"^\s*("
    r"第\s*\d+\s*页(\s*/\s*共\s*\d+\s*页)?"   # 第 12 页 / 共 80 页
    r"|"
    r"[\-—]\s*\d+\s*[\-—]"                       # -12-  / —12—
    r"|"
    r"Page\s+\d+(\s+of\s+\d+)?"                  # Page 12 of 80
    r"|"
    r"P[.\s]*\d+"                                 # P.12 / P 12
    r")\s*$",
    re.IGNORECASE,
)
_MIN_MEANINGFUL_CHARS = 4  # ultra-short orphan threshold (excluding whitespace)

# merge_continuation — only paragraphs whose tail is unfinished should be
# stitched. These are the punctuation marks that signal "this sentence is
# complete; do not merge across".
_SENTENCE_TERMINATORS: frozenset[str] = frozenset(
    "。！？；…!?;.\u3002\uff01\uff1f\uff1b"
    "”\"’'）)】］]」』》\u201d\u2019\uff09\uff3d\uff5d"
)
_MERGE_LOOKAHEAD_PAGES = 1  # only merge across a single page break

_TABLE_SEMANTIC_HINT_KEYS: tuple[str, ...] = (
    "semantic_table_type", "table_semantic_type", "table_kind", "table_role",
)
_TABLE_ATOMIC_HINTS: frozenset[str] = frozenset({
    "row_atomic", "record_table", "row_records", "atomic_rows",
})
_TABLE_NON_ATOMIC_HINTS: frozenset[str] = frozenset({
    "matrix", "cross_tab", "crosstab", "layout", "key_value", "form",
})
_RECORD_HEADER_KEYWORDS: frozenset[str] = frozenset({
    "时间", "日期", "发布", "年份", "年度", "部门", "机构", "单位",
    "文件", "名称", "标题", "内容", "摘要", "政策", "法规", "办法",
    "主体", "类型", "类别", "地区", "指标", "数值", "说明", "责任",
    "序号", "编号", "对象", "事项", "措施", "要求",
})
_STRONG_RECORD_HEADER_KEYWORDS: frozenset[str] = frozenset({
    "时间", "日期", "发布", "部门", "机构", "文件", "名称", "内容", "摘要", "政策",
})


# ---------------------------------------------------------------------------
# Operator 1: drop_navigational
# ---------------------------------------------------------------------------

def drop_navigational(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop blocks that should never become chunks.

    Removed:
      * any ``block_type in {"heading", "title"}`` — kept only as
        heading_path context by ``enrich_context``.
      * any block whose ``metadata.role == "document_metadata"`` — already
        on ``normalized_ref.document_metadata`` (slice 1).
      * legacy paragraph blocks whose text starts with ``#`` (back-compat
        for adapters that did not normalise to ``block_type=heading``).
    """
    kept: list[dict[str, Any]] = []
    for b in blocks:
        if (b.get("block_type") in _HEADING_TYPES):
            continue
        meta = b.get("metadata") or {}
        if meta.get("role") == "document_metadata":
            continue
        text = _text_of(b).lstrip()
        if text.startswith("#") and " " in text[:6] and b.get("block_type") == "paragraph":
            # legacy "# H1" paragraph — treat as heading, skip
            continue
        kept.append(b)
    return kept


# ---------------------------------------------------------------------------
# Operator 2: drop_meaningless (per-user explicit requirement)
# ---------------------------------------------------------------------------

def drop_meaningless(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop blocks that carry no retrievable semantic value.

    Rules (apply ONLY to ``paragraph`` blocks; structural blocks like
    ``table`` / ``chart`` / ``image`` / ``code`` are kept regardless of
    text length — their bbox + image alone is worth indexing):

    1. ``decorative=True`` or ``parse_quality="decorative"`` — already
       flagged by the parser.
    2. pure page numbers (``"12"``, ``"12 "``) or footer markers
       (``"- 12 -"``, ``"第 12 页 / 共 80 页"``, ``"Page 12 of 80"``).
    3. pure punctuation (no Chinese / English / digit characters at all).
    4. ultra-short orphans (< ``_MIN_MEANINGFUL_CHARS`` non-whitespace chars).

    Charts / images / tables are NEVER dropped here — even if their text is
    empty, the bbox + caption + image_uris remain a retrievable unit.
    """
    kept: list[dict[str, Any]] = []
    for b in blocks:
        btype = b.get("block_type")
        if b.get("decorative") is True or b.get("parse_quality") == "decorative":
            continue
        if btype in _MEDIA_TYPES:
            kept.append(b)
            continue
        text = _text_of(b).strip()
        if not text:
            # empty paragraph never carries meaning
            continue
        if _PAGE_FOOTER_RE.match(text):
            continue
        if _PURE_DIGITS_RE.match(text):
            continue
        if _PURE_PUNCT_RE.match(text):
            continue
        non_ws = re.sub(r"\s+", "", text)
        if len(non_ws) < _MIN_MEANINGFUL_CHARS:
            continue
        kept.append(b)
    return kept


# ---------------------------------------------------------------------------
# Operator 3: attach_attribution
# ---------------------------------------------------------------------------

def attach_attribution(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold short attribution paragraphs into the nearest adjacent media block.

    An attribution is a short (≤ ``_ATTRIBUTION_MAX_LEN`` chars) paragraph
    whose text matches one of ``_ATTRIBUTION_PATTERNS`` (``数据来源:`` /
    ``图 3-1`` / ``Source: ...`` ...). It folds into the **preceding** media
    block when one exists in the same page (or page+1); otherwise into the
    **following** media block within the same window. When no neighbouring
    media block exists, the attribution is kept as a standalone paragraph
    (better to surface it than silently drop it).

    Output blocks gain an ``attribution_children`` field on the media block
    so the locator builder can compute md_spans across the parent + folded
    attributions.
    """
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if not _is_attribution(b):
            out.append(b)
            i += 1
            continue
        # try preceding media block (within ±1 page)
        host = _find_host_in(out, b, direction=-1)
        if host is not None:
            _attach(host, b)
            i += 1
            continue
        # try following media block within the next 3 candidates
        host_idx = _scan_following_media(blocks, i + 1)
        if host_idx is not None:
            blocks[host_idx] = dict(blocks[host_idx])  # copy on write
            _attach(blocks[host_idx], b)
            i += 1
            continue
        # no host found — keep as standalone
        out.append(b)
        i += 1
    return out


def _is_attribution(block: dict[str, Any]) -> bool:
    if block.get("block_type") != "paragraph":
        return False
    text = _text_of(block).strip()
    if not text or len(text) > _ATTRIBUTION_MAX_LEN:
        return False
    return any(p.match(text) for p in _ATTRIBUTION_PATTERNS)


def _find_host_in(
    out: list[dict[str, Any]],
    attr: dict[str, Any],
    *,
    direction: int,
) -> dict[str, Any] | None:
    """Search ``out`` (already-emitted blocks) for the nearest media host."""
    a_page = attr.get("page")
    # scan backwards
    for cand in reversed(out):
        if cand.get("block_type") in _MEDIA_TYPES:
            c_page = cand.get("page")
            if (
                a_page is None
                or c_page is None
                or abs((a_page or 0) - (c_page or 0)) <= 1
            ):
                return cand
            return None  # too far away
        # do not jump over another non-media paragraph
        if cand.get("block_type") == "paragraph":
            return None
    return None


def _scan_following_media(
    blocks: list[dict[str, Any]],
    start: int,
) -> int | None:
    for j in range(start, min(start + 3, len(blocks))):
        if blocks[j].get("block_type") in _MEDIA_TYPES:
            return j
    return None


def _attach(host: dict[str, Any], attribution: dict[str, Any]) -> None:
    children = list(host.get("attribution_children") or [])
    children.append(attribution)
    host["attribution_children"] = children


# ---------------------------------------------------------------------------
# Operator 4: merge_continuation
# ---------------------------------------------------------------------------

def merge_continuation(
    blocks: list[dict[str, Any]],
    original_blocks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Stitch a paragraph whose last char is non-terminal with its successor.

    Triggered when ALL of:
      - ``blocks[i]`` and ``blocks[i+1]`` are both ``paragraph``;
      - ``blocks[i]``'s stripped text does NOT end with a sentence terminator
        in ``_SENTENCE_TERMINATORS``;
      - ``blocks[i+1]`` starts with a lowercase / Chinese character (not a
        bullet ``- `` / number ``1. `` / heading ``#``);
      - their pages differ by ≤ ``_MERGE_LOOKAHEAD_PAGES`` (so we only fix
        cross-page splits, not arbitrary same-page joins which are usually
        correctly segmented).

    Merged output is a single paragraph block with:
      * concatenated text (joined by ``""`` — true continuation, no extra
        whitespace);
      * ``merged_from = [block_id_a, block_id_b, ...]`` (used downstream by
        the locator builder to emit ``md_spans``);
      * inherits page=min_page, page_end=max_page, bbox union.
    """
    original_blocks = original_blocks or blocks
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.get("block_type") != "paragraph":
            out.append(b)
            i += 1
            continue
        merged = dict(b)
        merged.setdefault("merged_from", [b.get("block_id")])
        j = i + 1
        while j < len(blocks) and _should_merge(merged, blocks[j], original_blocks):
            nxt = blocks[j]
            merged["text"] = (merged.get("text") or "") + (nxt.get("text") or "")
            merged["merged_from"].append(nxt.get("block_id"))
            # page span widens; bbox union deferred to locator builder
            merged["page_end"] = nxt.get("page")
            # collect per-block details for md_spans
            sub = list(merged.get("_merged_blocks") or [b])
            sub.append(nxt)
            merged["_merged_blocks"] = sub
            j += 1
        # if no merging happened, _merged_blocks stays absent — keep block as-is
        if len(merged.get("merged_from", [])) > 1:
            out.append(merged)
        else:
            out.append(b)
        i = j
    return out


def _should_merge(
    prev: dict[str, Any],
    nxt: dict[str, Any],
    original_blocks: list[dict[str, Any]],
) -> bool:
    if nxt.get("block_type") != "paragraph":
        return False
    if _has_heading_between(prev, nxt, original_blocks):
        return False
    p_text = (prev.get("text") or "").rstrip()
    if not p_text:
        return False
    last_char = p_text[-1]
    if last_char in _SENTENCE_TERMINATORS:
        return False
    n_text = (nxt.get("text") or "").lstrip()
    if not n_text:
        return False
    # do not merge if next starts a list / numbered / heading-like line
    if n_text[0] in {"#", "-", "*", "•", "·"}:
        return False
    if re.match(r"^\d+[.、)）]\s", n_text):
        return False
    # page distance guard
    p_page = prev.get("page_end") if prev.get("page_end") is not None else prev.get("page")
    n_page = nxt.get("page")
    if p_page is not None and n_page is not None:
        if abs(n_page - p_page) > _MERGE_LOOKAHEAD_PAGES:
            return False
    return True


def _has_heading_between(
    prev: dict[str, Any],
    nxt: dict[str, Any],
    original_blocks: list[dict[str, Any]],
) -> bool:
    """Return True when a heading boundary sits between two candidate blocks."""
    prev_seq = prev.get("seq_no")
    nxt_seq = nxt.get("seq_no")
    if prev_seq is None or nxt_seq is None:
        return False
    lo, hi = sorted((prev_seq, nxt_seq))
    for block in original_blocks:
        if block.get("block_type") not in _HEADING_TYPES:
            continue
        seq = block.get("seq_no")
        if seq is not None and lo < seq < hi:
            return True
    return False


# ---------------------------------------------------------------------------
# Operator 5: decompose_atomic_tables
# ---------------------------------------------------------------------------

def decompose_atomic_tables(
    blocks: list[dict[str, Any]],
    *,
    body_markdown: str = "",
) -> list[dict[str, Any]]:
    """Split only row-record tables into overview + row-level candidates.

    A table is decomposed only when it is recognisably a record table:
    markdown pipe table, >=3 columns, >=2 data rows, field-like headers, and
    not a matrix / key-value / layout table. Callers can force the decision
    with block.metadata.semantic_table_type = "row_atomic" / "record_table",
    or force no-split with "matrix", "key_value", etc.
    """
    out: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("block_type") != "table":
            out.append(block)
            continue
        parsed = _parse_markdown_table(block.get("content") or "")
        if parsed is None or not _is_atomic_row_table(block, parsed):
            out.append(block)
            continue

        overview = dict(block)
        overview["content"] = _table_overview_text(parsed)
        overview["_unit_metadata"] = {
            "table_semantics": "row_atomic",
            "table_parent_block_id": block.get("block_id"),
            "table_row_count": len(parsed["data_rows"]),
            "table_columns": parsed["headers"],
        }
        out.append(overview)

        for row_index, row in enumerate(parsed["data_rows"], start=1):
            row_range = _row_md_range(block, row["raw"], body_markdown)
            source = _descriptor(block)
            source["md_char_range"] = row_range or block.get("md_char_range")
            row_unit = {
                "block_id": f"{block.get('block_id')}#row-{row_index}",
                "block_type": "table_row",
                "seq_no": block.get("seq_no"),
                "page": block.get("page"),
                "bbox": block.get("bbox"),
                "caption": block.get("caption"),
                "content": _table_row_text(block, parsed["headers"], row["cells"]),
                "_source_blocks": [source],
                "_unit_metadata": {
                    "table_semantics": "row_atomic",
                    "table_parent_block_id": block.get("block_id"),
                    "table_row_index": row_index,
                    "table_columns": parsed["headers"],
                    "table_row_cells": row["cells"],
                    "locator_precision": "markdown_row" if row_range else "table_block",
                },
            }
            out.append(row_unit)
    return out


def _parse_markdown_table(markdown: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    pipe_lines = [line for line in lines if "|" in line]
    if len(pipe_lines) < 3:
        return None

    header_idx: int | None = None
    for i in range(len(pipe_lines) - 1):
        header_cells = _split_table_row(pipe_lines[i])
        sep_cells = _split_table_row(pipe_lines[i + 1])
        if header_cells and sep_cells and _is_separator_row(sep_cells):
            header_idx = i
            break
    if header_idx is None:
        return None

    headers = [_normalise_cell(c) for c in _split_table_row(pipe_lines[header_idx])]
    if not headers or any(not h for h in headers):
        return None

    data_rows: list[dict[str, Any]] = []
    for raw in pipe_lines[header_idx + 2:]:
        cells = [_normalise_cell(c) for c in _split_table_row(raw)]
        if len(cells) != len(headers):
            continue
        if not any(cells):
            continue
        data_rows.append({"raw": raw, "cells": cells})

    data_rows = _merge_continuation_table_rows(headers, data_rows)
    if not data_rows:
        return None
    return {"headers": headers, "data_rows": data_rows}


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [part.strip() for part in stripped.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.match(r"^:?-{3,}:?$", c.strip()) for c in cells)


def _normalise_cell(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.replace("<br>", " / ").strip())


def _merge_continuation_table_rows(
    headers: list[str],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge markdown table continuation rows into the previous record row.

    Some PDF table extractors split a long cell across physical rows, yielding
    rows where all record-identifying columns are empty and only the final
    description cell has text. For row-atomic tables, those fragments are not
    standalone facts; they belong to the previous row.
    """
    merged: list[dict[str, Any]] = []
    for row in rows:
        cells = list(row["cells"])
        if merged and _is_continuation_table_row(headers, cells):
            prev = merged[-1]
            prev_cells = list(prev["cells"])
            for i, value in enumerate(cells):
                if not value:
                    continue
                if prev_cells[i]:
                    prev_cells[i] = f"{prev_cells[i]} {value}"
                else:
                    prev_cells[i] = value
            prev["cells"] = prev_cells
            prev["raw"] = f"{prev['raw']}\n{row['raw']}"
            prev["continuation_rows"] = [
                *(prev.get("continuation_rows") or []),
                row["raw"],
            ]
            continue
        merged.append(row)
    return merged


def _is_continuation_table_row(headers: list[str], cells: list[str]) -> bool:
    non_empty = [i for i, cell in enumerate(cells) if cell]
    if not non_empty:
        return False
    # A continuation row usually only has the last descriptive cell populated.
    if len(non_empty) == 1 and non_empty[0] == len(cells) - 1:
        return True

    identifier_indices = [
        i for i, header in enumerate(headers[:-1])
        if _has_any_keyword(header, _STRONG_RECORD_HEADER_KEYWORDS)
    ]
    if identifier_indices and all(not cells[i] for i in identifier_indices):
        # If all identifying columns are empty and only trailing descriptive
        # columns have text, treat it as a continuation of the previous record.
        return all(i >= max(identifier_indices) for i in non_empty)
    return False


def _is_atomic_row_table(block: dict[str, Any], parsed: dict[str, Any]) -> bool:
    hint = _table_semantic_hint(block)
    if hint in _TABLE_NON_ATOMIC_HINTS:
        return False
    if hint in _TABLE_ATOMIC_HINTS:
        return True

    headers = parsed["headers"]
    data_rows = parsed["data_rows"]
    if len(headers) < 3 or len(headers) > 10:
        return False
    if len(data_rows) < 2:
        return False
    if _looks_like_matrix_table(headers, data_rows):
        return False

    keyword_hits = sum(1 for h in headers if _has_any_keyword(h, _RECORD_HEADER_KEYWORDS))
    strong_hits = sum(1 for h in headers if _has_any_keyword(h, _STRONG_RECORD_HEADER_KEYWORDS))
    if strong_hits >= 2:
        return True
    if len(headers) >= 4 and strong_hits >= 1 and keyword_hits >= 2:
        return True
    return False


def _table_semantic_hint(block: dict[str, Any]) -> str | None:
    meta = block.get("metadata") or {}
    for key in _TABLE_SEMANTIC_HINT_KEYS:
        value = meta.get(key) or block.get(key)
        if value:
            return str(value).strip().lower()
    return None


def _has_any_keyword(text: str, keywords: frozenset[str]) -> bool:
    return any(k in text for k in keywords)


def _looks_like_matrix_table(headers: list[str], data_rows: list[dict[str, Any]]) -> bool:
    if len(headers) < 4:
        return False
    value_like = sum(1 for h in headers[1:] if _is_year_like(h) or len(h) <= 4)
    first = headers[0]
    if value_like >= max(3, len(headers[1:]) - 1) and first in {
        "项目", "类别", "类型", "地区", "指标", "维度", "名称",
    }:
        return True
    cells = [cell for row in data_rows for cell in row["cells"][1:]]
    if cells:
        numeric = sum(1 for cell in cells if _is_numeric_like(cell))
        if numeric / len(cells) >= 0.8 and value_like >= 2:
            return True
    return False


def _is_year_like(value: str) -> bool:
    return bool(re.match(r"^\d{4}(年)?$", value.strip()))


def _is_numeric_like(value: str) -> bool:
    v = value.strip().replace(",", "").replace("%", "")
    return bool(re.match(r"^-?\d+(\.\d+)?$", v))


def _row_md_range(
    block: dict[str, Any],
    raw_row: str,
    body_markdown: str,
) -> list[int] | None:
    block_range = block.get("md_char_range")
    if not body_markdown or not block_range or len(block_range) != 2:
        return None
    start, end = block_range
    haystack = body_markdown[start:end]
    idx = haystack.find(raw_row)
    if idx < 0:
        return None
    return [start + idx, start + idx + len(raw_row)]


def _table_overview_text(parsed: dict[str, Any]) -> str:
    headers = parsed["headers"]
    row_count = len(parsed["data_rows"])
    return f"表格概览：共 {row_count} 条记录；字段：{' / '.join(headers)}"


def _table_row_text(
    block: dict[str, Any],
    headers: list[str],
    cells: list[str],
) -> str:
    prefix = (block.get("caption") or "表格行记录").strip()
    pairs = [f"{h}: {c}" for h, c in zip(headers, cells) if c]
    return f"{prefix} | " + " | ".join(pairs)


# ---------------------------------------------------------------------------
# Operator 6: enrich_context → final SemanticUnit list
# ---------------------------------------------------------------------------

def enrich_context(
    candidates: list[dict[str, Any]],
    original_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert surviving candidate blocks into SemanticUnit dicts.

    Each unit carries:

    - ``content``: chunk text (after merge + attribution composition);
    - ``source_blocks``: list of contributing block descriptors
      (each ``{block_id, page, bbox, md_char_range, block_type}``);
    - ``heading_path``: list of ``{level, title}`` from current candidate's
      page position back through the **most recent** heading at each level
      (h1, h2, h3 only — deeper levels collapse into h3);
    - ``anchor_role``: one of ``body / table_overview / table_row / chart / image``;
    - ``caption``: optional caption text for media units;
    - ``md_spans``: present only when the unit was merged from multiple
      blocks (so the preview UI can highlight each span individually).
    """
    heading_index = _build_heading_index(original_blocks)
    units: list[dict[str, Any]] = []
    for cand in candidates:
        unit = _to_unit(cand, heading_index)
        if unit is not None:
            units.append(unit)
    return units


def _to_unit(
    cand: dict[str, Any],
    heading_index: list[tuple[int, dict[str, Any]]],
) -> dict[str, Any] | None:
    btype = cand.get("block_type")
    seq = cand.get("seq_no")
    heading_path = _heading_path_for(seq, heading_index)
    sources = _source_blocks_of(cand)
    if not sources:
        return None
    content = _content_for_unit(cand)
    if not content:
        return None
    anchor_role = _anchor_role_of(cand)
    caption = cand.get("caption") if btype in _MEDIA_TYPES else None

    # md_spans only meaningful for merged units OR media+attribution composites
    md_spans: list[dict[str, Any]] | None = None
    if cand.get("_merged_blocks"):
        md_spans = [_span_of(b) for b in cand["_merged_blocks"] if _span_of(b)]
    elif cand.get("attribution_children"):
        spans = [_span_of(cand)] + [_span_of(b) for b in cand["attribution_children"]]
        md_spans = [s for s in spans if s]
    if md_spans is not None and len(md_spans) < 2:
        md_spans = None

    return {
        "content": content,
        "source_blocks": sources,
        "heading_path": heading_path,
        "anchor_role": anchor_role,
        "caption": caption,
        "md_spans": md_spans,
        "metadata": cand.get("_unit_metadata") or {},
    }


def _content_for_unit(cand: dict[str, Any]) -> str:
    """Compose the chunk text from a candidate block + any attached attributions."""
    parts: list[str] = []
    btype = cand.get("block_type")
    primary = cand.get("text") or cand.get("content") or ""
    if cand.get("caption") and btype in _MEDIA_TYPES:
        parts.append(str(cand["caption"]))
    if primary:
        parts.append(str(primary))
    for child in cand.get("attribution_children") or []:
        ctext = (child.get("text") or "").strip()
        if ctext:
            parts.append(ctext)
    return "\n\n".join(p for p in parts if p)


def _source_blocks_of(cand: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten candidate (and its merged / attribution children) into descriptors."""
    if cand.get("_source_blocks"):
        return [d for d in cand["_source_blocks"] if d.get("block_id")]
    bag: list[dict[str, Any]] = []
    if cand.get("_merged_blocks"):
        for b in cand["_merged_blocks"]:
            bag.append(_descriptor(b))
    else:
        bag.append(_descriptor(cand))
    for child in cand.get("attribution_children") or []:
        bag.append(_descriptor(child))
    return [d for d in bag if d.get("block_id")]


def _descriptor(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_id": block.get("block_id"),
        "block_type": block.get("block_type"),
        "page": block.get("page"),
        "bbox": block.get("bbox"),
        "md_char_range": block.get("md_char_range"),
    }


def _span_of(block: dict[str, Any]) -> dict[str, Any] | None:
    r = block.get("md_char_range")
    if not r or len(r) != 2 or r[1] <= r[0]:
        return None
    return {"start": r[0], "end": r[1], "block_id": block.get("block_id")}


def _anchor_role_of(cand: dict[str, Any]) -> str:
    btype = cand.get("block_type")
    if btype == "table":
        return "table_overview"
    if btype == "table_row":
        return "table_row"
    if btype == "chart":
        return "chart"
    if btype == "image":
        return "image"
    if btype == "equation":
        return "equation"
    return "body"


# ---------------------------------------------------------------------------
# heading_path index (built once per document)
# ---------------------------------------------------------------------------

def _build_heading_index(
    blocks: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    """Index ``(seq_no, heading_dict)`` for every heading block, ordered by seq."""
    out: list[tuple[int, dict[str, Any]]] = []
    for b in blocks:
        if b.get("block_type") not in _HEADING_TYPES:
            continue
        seq = b.get("seq_no")
        if seq is None:
            continue
        level = b.get("heading_level") or _level_from_hashes(_text_of(b))
        title = _strip_heading(_text_of(b))
        out.append((seq, {"level": int(level or 2), "title": title}))
    return out


def _heading_path_for(
    seq: int | None,
    index: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Return the h1→h2→h3 stack active at the given seq_no."""
    if seq is None:
        return []
    # collapse to most-recent heading per level (1..3)
    by_level: dict[int, dict[str, Any]] = {}
    for hseq, h in index:
        if hseq > seq:
            break
        lvl = h["level"]
        if lvl > 3:
            lvl = 3  # squash deeper levels into h3 slot
        # clear deeper-level entries when a higher-level heading appears
        for cleared in [l for l in list(by_level) if l > lvl]:
            by_level.pop(cleared, None)
        by_level[lvl] = {"level": lvl, "title": h["title"]}
    return [by_level[k] for k in sorted(by_level.keys())]


def _level_from_hashes(text: str) -> int:
    s = text.lstrip()
    n = 0
    while n < len(s) and s[n] == "#":
        n += 1
    return max(1, min(n, 6)) if n else 2


def _strip_heading(text: str) -> str:
    return text.lstrip().lstrip("#").strip()


# ---------------------------------------------------------------------------
# Utility & main entry
# ---------------------------------------------------------------------------

def _text_of(block: dict[str, Any]) -> str:
    return str(block.get("text") or block.get("content") or "")


def repack(
    blocks: list[dict[str, Any]],
    body_markdown: str = "",
) -> list[dict[str, Any]]:
    """Run the full semantic_repack pipeline.

    Returns a list of ``SemanticUnit`` dicts (see :func:`_to_unit`).
    ``body_markdown`` is currently unused (md_char_range is already on each
    block) but kept in the signature so the caller can plumb it through for
    future enrichment without another refactor.
    """
    if not blocks:
        return []
    n0 = len(blocks)
    step1 = drop_navigational(blocks)
    step2 = drop_meaningless(step1)
    step3 = attach_attribution(step2)
    step4 = merge_continuation(step3, original_blocks=blocks)
    step5 = decompose_atomic_tables(step4, body_markdown=body_markdown)
    units = enrich_context(step5, original_blocks=blocks)
    logger.info(
        "semantic_repack: in=%d nav-drop→%d meaningless-drop→%d "
        "attribution-fold→%d merge→%d table-decompose→%d units=%d body_md_len=%d",
        n0, len(step1), len(step2), len(step3), len(step4), len(step5),
        len(units), len(body_markdown),
    )
    return units
