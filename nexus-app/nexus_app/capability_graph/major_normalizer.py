"""A1f (§10 阶段 A + §1.13 §1.15 决策) — major_name/major_code normalization.

The existing identity extractors (`teaching_standard.extractor._major_identity`
and `major_profile.extractor._extract_identity`) return `(major_code,
major_name)` tuples where `major_name` sometimes swallows the asset-type
suffix — e.g. the teaching-standard extractor returns "电子商务专业教学标准"
for a document titled "5307 电子商务专业教学标准" (test_teaching_standard_graph.py:33).

That value is fine for the source domain rows but wrong for
`build.major_name`, which the A1f `/by-major` endpoint uses as a
substring-matching business key. We need "电子商务" so that a query
`major_name=电子商务` naturally matches both the teaching_standard
build ("电子商务") and the ability_analysis build ("电子商务类" →
normalized to "电子商务" as well).

Two normalization steps, applied in order:

1. Strip asset-type suffixes (longest-first — "职业教育专业教学标准"
   must match before "教学标准" so the shorter form doesn't eat
   the prefix).
2. Strip a trailing single "类" (`"电子商务类"` → `"电子商务"`) but
   preserve "大类" (`"财经商贸大类"` stays intact). The negative
   look-behind `(?<!大)` keeps the compound word.

Returns `None` for empty / whitespace-only inputs so the caller can
short-circuit and leave `build.major_name` unpopulated (better than an
empty string that would silently match every substring query).
"""
from __future__ import annotations

import re

# Longest-first ordering matters — `re.sub` matches greedily, so if
# "教学标准" appeared before "职业教育专业教学标准" we'd chop off the
# suffix mid-word.
_ASSET_TYPE_SUFFIXES: tuple[str, ...] = (
    # Teaching standard (§1.13 §5 list)
    "职业教育专业教学标准",
    "中等职业教育专业教学标准",
    "高等职业教育专科专业教学标准",
    "专业教学标准",
    "教学标准",
    # Major profile
    "院校专业简介",
    "专业简介",
    # Ability analysis
    "职业能力分析表",
    "能力分析表",
)

# Sorted longest-first — regex alternation is greedy but Python's `re`
# module does *first-match* alternation not longest-match, so we sort
# explicitly and build the alternation in that order.
_ASSET_TYPE_ALTERNATION = "|".join(
    re.escape(s)
    for s in sorted(_ASSET_TYPE_SUFFIXES, key=len, reverse=True)
)
_ASSET_TYPE_TRAILING_RE = re.compile(
    rf"(?:{_ASSET_TYPE_ALTERNATION})$"
)

# Trailing "类" but not "大类". The negative lookbehind guards the
# compound "大类" from being partially stripped.
_TRAILING_CLASS_RE = re.compile(r"(?<!大)类$")


def normalize_major_name(raw: str | None) -> str | None:
    """Strip asset-type suffixes and the trailing "类" from a major_name.

    Idempotent: passing an already-normalized name through a second time
    returns the same string.

    Preserves parenthesized qualifiers ("电子商务（跨境方向）") — those
    convey business meaning and belong in `build.major_name`.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    # Step 1: strip asset-type suffix (may run twice if the extractor
    # accidentally left both "教学标准" and "专业教学标准" nested).
    # Two passes is enough — the suffix table doesn't contain any
    # entries that overlap after one strip.
    for _ in range(2):
        stripped = _ASSET_TYPE_TRAILING_RE.sub("", value)
        if stripped == value:
            break
        value = stripped.strip()
    # Step 2: trailing single "类" → drop, unless it's the "大类"
    # compound (see the negative lookbehind).
    value = _TRAILING_CLASS_RE.sub("", value).strip()
    return value or None


def normalize_major_code(raw: str | None) -> str | None:
    """Whitespace-trim and validate the identity extractor's major_code.

    Returns `None` when the value is empty, whitespace, or doesn't look
    like a 4-6 digit code — protects `build.major_code` from bad values
    that would break the endpoint's Pattern validator downstream.
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if not re.fullmatch(r"\d{4,6}", value):
        return None
    return value


__all__ = [
    "normalize_major_code",
    "normalize_major_name",
]
