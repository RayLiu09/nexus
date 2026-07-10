"""Cross-link normalisation for tag_asset_index — v1.3 R3 unbreakable
invariant I-1 (see ``docs/tag_filter_reliability_matrix_v1.md §3``).

All four call sites in the tag_filter chain **must** share this one
function:

1. **intent side** — the raw ``cross_asset_tags`` produced by
   ``intent_recognition_v1_3`` is normalised before it flows into a
   ``RetrievalPlan.tag_filters``.
2. **L1.5 matcher** — ``TagAssetIndexResolver`` normalises each user-side
   candidate before the exact-lookup pass.
3. **projection hook** — every ``tag_asset_index`` write persists the
   normalised form into ``tag_value_normalized`` so L1 lookups don't
   have to re-normalise on the read path.
4. **resolver reverse lookup** — the same normalisation is applied to any
   `binding_map` output flowing back into a downstream sub_query.

If any call site derives its own normalisation, the L1 exact-match
guarantee silently breaks and downstream ``target_ids`` sets diverge.
The public API here is intentionally minimal: one function, one contract.

Rules (v1.3 §3.2 L1.5 起步版本):

* Unicode NFKC normalisation (halfwidth/fullwidth, simplified/traditional).
* Case fold to lowercase (English).
* Collapse internal whitespace and trim.
* Strip content in Chinese/ASCII brackets (``（含 XX）`` / ``(with X)``).
* Optionally strip common domain-specific suffixes (``市 / 省 / 区``
  for regions; ``业`` for industries; etc.), driven by ``tag_type``.
* Expand curated short forms (``京 → 北京`` / ``沪 → 上海`` etc.) so the
  L1 layer sees the canonical long form regardless of user input.

Non-goals:

* Semantic similarity — that's L4 (``tag_embedding``).
* Alias dictionaries with business-owned entries — those go through the
  L2 layer using ``dim_*_alias`` tables (see v1.3 §4.3).
* Reversibility — normalisation is one-way; the un-normalised value is
  kept on the persistent ``tag_asset_index.tag_value`` column for display.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Final, Literal

__all__ = [
    "TagTypeCode",
    "SUFFIX_STRIP_RULES",
    "SHORT_FORM_EXPANSIONS",
    "normalize_tag_value",
    "denormalize_debug",
]


# ---------------------------------------------------------------------------
# Type alias mirrors ai_governance.tag_taxonomy.TagTypeCode; local so this
# module has zero import dependencies on the rest of ai_governance and can
# be safely used by the projection hook, resolver, and intent layer.
# ---------------------------------------------------------------------------

TagTypeCode = Literal[
    "region", "industry", "occupation", "major", "ability", "topic", "time_range"
]


# ---------------------------------------------------------------------------
# Curated tables.  Keep small — L2 (alias dictionaries maintained in the
# console) is the extensible layer.  These live in code because they
# express *linguistic* invariants that never change per tenant.
# ---------------------------------------------------------------------------


# Per-tag_type common suffixes that are safe to strip when comparing.
# Empty tuple means "no suffix stripping for this type".
SUFFIX_STRIP_RULES: Final[dict[TagTypeCode, tuple[str, ...]]] = {
    # Regions: 北京市 → 北京, 广东省 → 广东, 朝阳区 → 朝阳.
    #          "自治区" stripped before "区" to avoid clipping "内蒙古自治区" to
    #          "内蒙古自治" (order matters — longer suffix wins).
    "region": ("自治区", "特别行政区", "县级市", "省", "市", "区", "县", "州", "盟"),
    "industry": (),
    "occupation": (),
    "major": (),
    "ability": (),
    "topic": (),
    "time_range": (),
}


# Curated short-form → canonical expansion.  Only include forms that are
# *unambiguous* in the target vocabulary — if a short form has multiple
# reasonable expansions (e.g. "华南" → several provinces) we do NOT expand
# it here; it stays for L2/L4 to disambiguate.
#
# ~30-entry cap on this table: growth pressure should route through the
# dim_*_alias tables instead.
SHORT_FORM_EXPANSIONS: Final[dict[str, str]] = {
    # 省份简称 (canonical 长形式)
    "京": "北京",
    "沪": "上海",
    "津": "天津",
    "渝": "重庆",
    "粤": "广东",
    "浙": "浙江",
    "苏": "江苏",
    "闽": "福建",
    "鲁": "山东",
    "冀": "河北",
    "豫": "河南",
    "皖": "安徽",
    "赣": "江西",
    "湘": "湖南",
    "鄂": "湖北",
    "川": "四川",
    "黔": "贵州",
    "滇": "云南",
    "陕": "陕西",
    "甘": "甘肃",
    "青": "青海",
    "宁": "宁夏",
    "新": "新疆",
    "藏": "西藏",
    "桂": "广西",
    "蒙": "内蒙古",
    "辽": "辽宁",
    "吉": "吉林",
    "黑": "黑龙江",
    "琼": "海南",
    "港": "香港",
    "澳": "澳门",
    "台": "台湾",
}


# Chinese + ASCII bracket pairs.  Nested brackets are handled by the
# non-greedy regex.
_BRACKET_STRIP_RE = re.compile(
    r"(?:"
    r"\uff08[^\uff08\uff09]*\uff09"  # （…）Chinese fullwidth
    r"|\([^()]*\)"                    # (…) ASCII
    r"|\uff3b[^\uff3b\uff3d]*\uff3d"  # ［…］ Chinese square
    r"|\[[^\[\]]*\]"                  # […] ASCII
    r"|\uff5b[^\uff5b\uff5d]*\uff5d"  # ｛…｝ Chinese curly
    r"|\{[^{}]*\}"                    # {…} ASCII
    r")"
)


# Collapse any Unicode whitespace to zero (Chinese tags rarely need internal
# spaces; treating them as noise gives the most reliable L1 match).
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_tag_value(
    value: Any,
    tag_type: TagTypeCode | str | None = None,
) -> str:
    """Return the canonical form used for L1/L1.5 exact matching.

    The transform is deterministic and pure — call it in intent layer,
    L1.5 matcher, projection hook, and Resolver reverse lookup **without
    re-implementing any part**.

    Parameters
    ----------
    value:
        Any raw input.  Non-string values are stringified via ``str(...)``
        to keep the call site simple; a genuine ``None`` normalises to the
        empty string (not a crash, so that ``optional=True`` tag_filters
        can silently pass through empty inputs).
    tag_type:
        Optional taxonomy code.  Enables per-type suffix stripping — the
        only per-type step in the pipeline.  ``None`` means "generic"
        (no suffix stripping).  Unknown codes are treated as generic
        (rather than raising) so a future tag_type addition doesn't crash
        old call sites — the tag_taxonomy static guard catches the missing
        code at test time instead.

    Returns
    -------
    str
        The normalised form.  May be ``""`` if the input collapses to
        empty; call sites should treat empty as "no candidate", not as
        a match against empty rows.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)

    # 1. Unicode NFKC — halfwidth/fullwidth + compatibility decomposition.
    text = unicodedata.normalize("NFKC", value)

    # 2. Strip bracket content (repeat once to handle sibling brackets).
    prev = None
    while prev != text:
        prev = text
        text = _BRACKET_STRIP_RE.sub("", text)

    # 3. Collapse whitespace — Chinese tags rarely carry semantic spaces.
    text = _WHITESPACE_RE.sub("", text)

    # 4. Case fold English portions.  Chinese is unaffected.
    text = text.lower()

    # 5. Per-type suffix stripping (longest match wins).
    if tag_type is not None:
        suffixes = SUFFIX_STRIP_RULES.get(tag_type, ())  # type: ignore[arg-type]
        if suffixes:
            for suffix in sorted(suffixes, key=len, reverse=True):
                if text.endswith(suffix) and len(text) > len(suffix):
                    text = text[: -len(suffix)]
                    break

    # 6. Short-form expansion — applied *after* suffix stripping so that
    #    "京市" (unusual) normalises to "京" then expands to "北京".
    if text in SHORT_FORM_EXPANSIONS:
        text = SHORT_FORM_EXPANSIONS[text]

    # Trim outer whitespace once more (in case a suffix removal exposed
    # some).
    return text.strip()


def denormalize_debug(
    original: Any,
    normalised: str,
    tag_type: TagTypeCode | str | None = None,
) -> dict[str, Any]:
    """Return a per-rule execution trace — for the Console 'why did my tag
    match / not match' panel and for CI diagnostics.  Not on the hot path.

    Callers should compare against ``normalize_tag_value(original, tag_type)``;
    if they diverge, the tag has drifted and rebuilding tag_asset_index is
    likely required.
    """
    return {
        "original": original,
        "tag_type": tag_type,
        "normalised": normalised,
        "matches_current_rule_set": (
            normalize_tag_value(original, tag_type) == normalised
        ),
    }
