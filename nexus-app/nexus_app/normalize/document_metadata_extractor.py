"""Document-level metadata extractor.

Pulls document-level fields (title, authors, publish_date, keywords, abstract,
outline) out of ``normalized_ref.blocks`` so they live ONCE on the
``NormalizedAssetRef`` (column ``document_metadata``) instead of being
duplicated into every per-chunk metadata downstream.

Belongs to slice 0+1 of docs/rag_semantic_chunks_implementation_plan.md.
The extractor is rule-driven (v1); LLM fallback can be added in v2 without
changing this module's call contract.

The returned mapping mirrors the schema in
docs/blocks_to_rag_chunks_optimization.md §三.3:

    {
        "title":         str | None,
        "subtitle":      str | None,
        "authors":       list[str],
        "publish_date":  str | None,        # ISO yyyy[-mm[-dd]]
        "publisher":     str | None,
        "doc_number":    str | None,
        "version":       str | None,
        "language":      str | None,
        "keywords":      list[str],
        "abstract":      str | None,
        "outline":       list[dict],        # copied from payload.toc
        "source_block_ids": list[str],
    }

Block-side bookkeeping: the IDs of blocks that contributed to metadata
extraction are returned alongside the metadata dict so the upstream
caller can stamp ``role=document_metadata`` on those blocks. The semantic
repack layer (slice 2) skips any block whose role is so marked, ensuring
title / authors / etc. are NEVER produced as standalone RAG chunks.

Public API:

    extract(blocks, body_markdown, toc) -> tuple[dict, set[str]]
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Heading detector — block_type=heading is the most reliable signal, but for
# back-compat we also accept paragraph blocks whose text starts with "# ".
def _is_heading(block: dict[str, Any]) -> bool:
    if block.get("block_type") == "heading":
        return True
    text = (block.get("text") or block.get("content") or "").lstrip()
    return text.startswith("#") and " " in text[:6]


def _block_text(block: dict[str, Any], body_markdown: str) -> str:
    """Resolve a block's text — prefer .text, fall back to md_char_range slice."""
    txt = block.get("text") or block.get("content") or ""
    if txt:
        return txt
    rng = block.get("md_char_range")
    if rng and isinstance(rng, (list, tuple)) and len(rng) == 2:
        return body_markdown[rng[0]:rng[1]]
    return ""


_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})?\s*日?\s*$"),
    re.compile(r"^\s*(\d{4})-(\d{1,2})(?:-(\d{1,2}))?\s*$"),
    re.compile(r"^\s*(\d{4})\.(\d{1,2})(?:\.(\d{1,2}))?\s*$"),
    re.compile(r"^\s*(\d{4})/(\d{1,2})(?:/(\d{1,2}))?\s*$"),
)


def _parse_publish_date(text: str) -> str | None:
    s = text.strip()
    for pat in _DATE_PATTERNS:
        m = pat.match(s)
        if m:
            y = int(m.group(1))
            mo = int(m.group(2))
            d = m.group(3)
            if d:
                return f"{y:04d}-{mo:02d}-{int(d):02d}"
            return f"{y:04d}-{mo:02d}"
    return None


_KEYWORDS_RE = re.compile(r"^\s*关键词\s*[:：]\s*(.+?)\s*[。.]?\s*$")
_KEYWORDS_SPLIT_RE = re.compile(r"[；;，,、\s]+")

_AUTHOR_SUFFIXES = (
    "中心", "研究院", "课题组", "委员会", "工作组", "实验室",
    "学院", "学会", "协会", "联合会", "基金会", "研究所", "智库",
)

_DOC_NUMBER_RE = re.compile(r"^\s*([A-Z]{2,}[\s-]*\d{1,4}[\s-]*[—-]?[\s-]*\d{0,4})\s*$")


def _looks_like_author(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 60:
        return False
    return any(t.endswith(suf) for suf in _AUTHOR_SUFFIXES)


def _looks_like_publisher(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 80:
        return False
    return any(
        kw in t
        for kw in ("出版社", "出版集团", "Press", "press")
    )


def extract(
    blocks: list[dict[str, Any]],
    body_markdown: str,
    toc: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], set[str]]:
    """Run rule-based extraction over the leading blocks of the document.

    Returns:
        (metadata, source_block_ids) — `metadata` is the document-level dict
        suitable for ``normalized_ref.document_metadata``; `source_block_ids`
        is the set of block IDs whose content contributed (caller stamps
        ``role=document_metadata`` on them).
    """
    metadata: dict[str, Any] = {
        "title": None,
        "subtitle": None,
        "authors": [],
        "publish_date": None,
        "publisher": None,
        "doc_number": None,
        "version": None,
        "language": None,
        "keywords": [],
        "abstract": None,
        "outline": [],
        "source_block_ids": [],
    }
    contributed: set[str] = set()
    if not blocks:
        return metadata, contributed

    # ---- 1. Title — first h1 heading, anywhere in the leading 5 blocks ----
    title_block_idx: int | None = None
    for i, b in enumerate(blocks[:5]):
        if _is_heading(b):
            text = _block_text(b, body_markdown).lstrip()
            cleaned = text.lstrip("#").strip()
            if cleaned:
                metadata["title"] = cleaned
                title_block_idx = i
                contributed.add(b.get("block_id"))
                break

    # ---- 2. Walk forward from title until first h2 (## section heading),
    #         collecting short author / publisher / date paragraphs. ----
    abstract_start_idx: int | None = None
    if title_block_idx is not None:
        for i in range(title_block_idx + 1, len(blocks)):
            b = blocks[i]
            if _is_heading(b):
                text = _block_text(b, body_markdown).lstrip()
                # second h1 (rare) or first h2 marks end of cover block
                if text.startswith("#"):
                    abstract_start_idx = i
                    break
                continue
            raw = _block_text(b, body_markdown).strip()
            if not raw:
                continue
            # publish date?
            d = _parse_publish_date(raw)
            if d and metadata["publish_date"] is None:
                metadata["publish_date"] = d
                contributed.add(b.get("block_id"))
                continue
            # author / institution?
            if _looks_like_author(raw):
                if raw not in metadata["authors"]:
                    metadata["authors"].append(raw)
                contributed.add(b.get("block_id"))
                continue
            # publisher?
            if _looks_like_publisher(raw) and metadata["publisher"] is None:
                metadata["publisher"] = raw
                contributed.add(b.get("block_id"))
                continue
            # doc number (e.g. GB/T 12345-2024) — narrow regex avoids
            # matching policy filenames such as "2025.12 ..."
            m = _DOC_NUMBER_RE.match(raw)
            if m and metadata["doc_number"] is None:
                metadata["doc_number"] = m.group(1).strip()
                contributed.add(b.get("block_id"))
                continue
            # bail out of cover detection at the first "real" paragraph
            # (≥ 80 chars typically signals body content).
            if len(raw) >= 80:
                abstract_start_idx = i
                break

    # ---- 3. Abstract — content between "## 导论" / "## 摘要" / "## 前言" and
    #         the next h2; aggregate consecutive paragraphs. ----
    ABSTRACT_HEADERS = ("导论", "摘要", "前言", "概述", "引言", "Abstract", "Summary")
    abstract_lines: list[str] = []
    capturing_abstract = False
    for b in blocks[: max(50, (abstract_start_idx or 0) + 25)]:
        if _is_heading(b):
            text = _block_text(b, body_markdown).strip().lstrip("#").strip()
            if any(h in text for h in ABSTRACT_HEADERS):
                capturing_abstract = True
                contributed.add(b.get("block_id"))
                continue
            if capturing_abstract:
                # next heading ends abstract
                break
            continue
        if capturing_abstract:
            raw = _block_text(b, body_markdown).strip()
            if not raw:
                continue
            # Stop if we hit the keywords line (it'll be handled separately).
            if _KEYWORDS_RE.match(raw):
                break
            abstract_lines.append(raw)
            contributed.add(b.get("block_id"))
    if abstract_lines:
        metadata["abstract"] = "\n\n".join(abstract_lines)

    # ---- 4. Keywords — explicit "关键词：A；B；C" line, scan first 30 blocks. ----
    for b in blocks[:30]:
        if _is_heading(b):
            continue
        raw = _block_text(b, body_markdown).strip()
        if not raw:
            continue
        m = _KEYWORDS_RE.match(raw)
        if m:
            parts = [p for p in _KEYWORDS_SPLIT_RE.split(m.group(1)) if p]
            if parts:
                metadata["keywords"] = parts
                contributed.add(b.get("block_id"))
            break

    # ---- 5. Outline — pass-through from payload.toc (already extracted by
    #         §12 TOC pass in mineru_converter). ----
    if toc:
        metadata["outline"] = list(toc)

    # ---- 6. Language hint — inherit ref.language at callsite, not here. ----

    metadata["source_block_ids"] = sorted(contributed)
    logger.info(
        "document_metadata: title=%s authors=%d publish_date=%s "
        "keywords=%d outline=%d abstract=%dchars contributed=%d",
        (metadata["title"] or "")[:40],
        len(metadata["authors"]),
        metadata["publish_date"],
        len(metadata["keywords"]),
        len(metadata["outline"]),
        len(metadata.get("abstract") or ""),
        len(contributed),
    )
    return metadata, contributed
