"""Deterministic outline builder.

Takes a flat list of headings (already extracted from MinerU output) and
produces a 3-level outline tree. Pure: no I/O, no DB, no LLM.

Rules
-----
* Root synthesized at ``level=0``.
* Heading levels normalized so the shallowest heading becomes ``level=1``.
* Depth truncated to 3: any heading whose depth would exceed 3 collapses
  under its nearest ancestor at level ≤ 3 (its content chunks still attach
  to that ancestor if it becomes a leaf).
* ``anchor_range`` and ``chunk_ids`` are cleared on non-leaf nodes; only
  leaves carry them.
* Fallback: when no headings are recognized, a single root node is emitted
  with ``fallback_used=True``.

Numbering parsing supports "1.2.3", 第X章, 第X节, 项目/模块/单元 X, and
``Chapter N`` — resulting in a ``numbering_path`` (list[int]) usable as a
lexicographic sort key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

MAX_DEPTH = 3


@dataclass(frozen=True)
class HeadingInput:
    """One MinerU heading with content span. Ordered top-to-bottom by caller."""

    title: str
    level: int
    # {start, end, page_start, page_end, ...} — opaque to the builder.
    anchor_range: dict[str, Any] | None = None
    source_block_ids: list[str] = field(default_factory=list)
    # Chunks whose content sits directly under this heading (before next heading).
    chunk_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutlineNodeSpec:
    """Materializable outline node, not yet a DB row."""

    id: str
    parent_id: str | None
    level: int
    order_index: int
    title: str
    numbering: str | None
    numbering_path: list[int] | None
    anchor_range: dict[str, Any] | None
    chunk_ids: list[str]
    source_block_ids: list[str]


@dataclass(frozen=True)
class OutlineBuildResult:
    build_run_id: str
    root: OutlineNodeSpec
    nodes: list[OutlineNodeSpec]
    fallback_used: bool
    total_nodes: int
    max_depth: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_outline(
    headings: list[HeadingInput],
    *,
    root_title: str,
    build_run_id: str | None = None,
) -> OutlineBuildResult:
    """Build a 3-level outline tree from a flat heading list.

    ``root_title`` is used only for the synthesized root. If ``headings`` is
    empty, returns a fallback single-node tree.
    """
    run_id = build_run_id or _new_uuid()

    if not headings:
        root = OutlineNodeSpec(
            id=_new_uuid(),
            parent_id=None,
            level=0,
            order_index=0,
            title=root_title or "全文",
            numbering=None,
            numbering_path=None,
            anchor_range=None,
            chunk_ids=[],
            source_block_ids=[],
        )
        return OutlineBuildResult(
            build_run_id=run_id,
            root=root,
            nodes=[root],
            fallback_used=True,
            total_nodes=1,
            max_depth=0,
        )

    normalized = _normalize_levels(headings)

    root = OutlineNodeSpec(
        id=_new_uuid(),
        parent_id=None,
        level=0,
        order_index=0,
        title=root_title,
        numbering=None,
        numbering_path=None,
        anchor_range=None,
        chunk_ids=[],
        source_block_ids=[],
    )
    nodes: list[OutlineNodeSpec] = [root]
    sibling_counts: dict[str | None, int] = {None: 1}  # id -> next order_index

    # Stack of (node, display_level). Everything past MAX_DEPTH caps to
    # MAX_DEPTH; capped headings become L3 siblings of the original L3
    # (not nested under it), keeping the outline strictly 3-level while
    # preserving every heading's identity and chunk association.
    stack: list[tuple[OutlineNodeSpec, int]] = [(root, 0)]

    for heading in normalized:
        target_level = min(heading.level, MAX_DEPTH)

        while len(stack) > 1 and stack[-1][1] >= target_level:
            stack.pop()

        parent_node, _ = stack[-1]
        order_index = sibling_counts.get(parent_node.id, 0)
        sibling_counts[parent_node.id] = order_index + 1

        numbering, numbering_path = parse_numbering(heading.title)

        node = OutlineNodeSpec(
            id=_new_uuid(),
            parent_id=parent_node.id,
            level=target_level,
            order_index=order_index,
            title=heading.title.strip(),
            numbering=numbering,
            numbering_path=numbering_path,
            anchor_range=heading.anchor_range,
            chunk_ids=list(heading.chunk_ids),
            source_block_ids=list(heading.source_block_ids),
        )
        nodes.append(node)
        stack.append((node, target_level))

    # Enforce leaf-only anchor_range + chunk_ids.
    has_children: set[str] = {
        n.parent_id for n in nodes if n.parent_id is not None
    }
    finalized = [
        replace(
            n,
            anchor_range=None if n.id in has_children else n.anchor_range,
            chunk_ids=[] if n.id in has_children else n.chunk_ids,
        )
        for n in nodes
    ]

    max_depth = max(n.level for n in finalized)
    return OutlineBuildResult(
        build_run_id=run_id,
        root=finalized[0],
        nodes=finalized,
        fallback_used=False,
        total_nodes=len(finalized),
        max_depth=max_depth,
    )


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------

# "1.2.3" style — greedy but bounded to 4 segments to avoid over-matching.
_NUMERIC_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,3})[\s、.\-)]")
_CHAPTER_CN_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十百千万零〇两\d]+)\s*章")
_SECTION_CN_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十百千万零〇两\d]+)\s*节")
_UNIT_CN_RE = re.compile(
    r"^\s*(?:项目|模块|单元)\s*([一二三四五六七八九十百千万零〇两\d]+)"
)
_CHAPTER_EN_RE = re.compile(
    r"^\s*Chapter\s+(\d+)\b", re.IGNORECASE,
)


def parse_numbering(title: str) -> tuple[str | None, list[int] | None]:
    """Extract a numbering token and its integer path from a heading title.

    Returns ``(None, None)`` if no numbering pattern is recognized.
    ``numbering_path`` is intended for lexicographic sorting.
    """
    if not title:
        return None, None

    stripped = title.lstrip()

    # Prefer the most specific numeric form first: "1.2.3" style.
    m = _NUMERIC_RE.match(stripped + " ")  # trailing space simplifies boundary
    if m:
        raw = m.group(1)
        parts = [int(p) for p in raw.split(".") if p]
        if parts:
            return raw, parts

    m = _CHAPTER_CN_RE.match(stripped)
    if m:
        raw = m.group(1)
        value = _to_int(raw)
        if value is not None:
            return f"第{raw}章", [value]

    m = _SECTION_CN_RE.match(stripped)
    if m:
        raw = m.group(1)
        value = _to_int(raw)
        if value is not None:
            return f"第{raw}节", [value]

    m = _UNIT_CN_RE.match(stripped)
    if m:
        raw = m.group(1)
        value = _to_int(raw)
        if value is not None:
            return raw, [value]

    m = _CHAPTER_EN_RE.match(stripped)
    if m:
        raw = m.group(1)
        return f"Chapter {raw}", [int(raw)]

    return None, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_levels(headings: list[HeadingInput]) -> list[HeadingInput]:
    """Shift levels so the shallowest heading becomes level 1."""
    min_level = min(h.level for h in headings)
    if min_level == 1:
        return list(headings)
    shift = 1 - min_level
    return [replace(h, level=max(1, h.level + shift)) for h in headings]


_CN_DIGITS: dict[str, int] = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _to_int(raw: str) -> int | None:
    """Parse a mixed CJK/ASCII numeral. Small numbers only (<10000)."""
    if not raw:
        return None
    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return None
    return _chinese_to_int(raw)


def _chinese_to_int(raw: str) -> int | None:
    """Convert small CJK numerals (up to 千万 range) to int.

    Handles common textbook forms: 一, 十, 十一, 二十, 二十一, 一百, 一百零一,
    两百, 三千. Not a full CJK numeral parser — returns ``None`` for edge
    cases so callers keep the raw form.
    """
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    current = 0
    last_unit = 0
    for ch in raw:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch in units:
            unit = units[ch]
            if current == 0 and unit == 10:
                # 「十」at start means 10.
                current = 1
            total += current * unit
            current = 0
            last_unit = unit
        else:
            return None
    if current:
        # Trailing lone digit: interpret positionally relative to last unit.
        if last_unit >= 10:
            total += current
        else:
            total += current
    return total if total > 0 else None


def _new_uuid() -> str:
    return str(uuid4())
