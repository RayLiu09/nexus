"""A1f (§10 阶段 A + §1.13) — major_normalizer unit tests.

Covers the 11 inline title samples enumerated in the task package plus
edge cases (whitespace, idempotency, "大类" preservation, bogus
major_code values).
"""
from __future__ import annotations

import pytest

from nexus_app.capability_graph.major_normalizer import (
    normalize_major_code,
    normalize_major_name,
)


# ---------------------------------------------------------------------------
# 11 golden samples — must match task package §1.13 交付物 ③ 内联样本
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # #1 — title "5307 电子商务专业教学标准" → extractor may return
        # "电子商务专业教学标准" (test_teaching_standard_graph.py:33 shows
        # the current bug); normalizer must recover "电子商务".
        ("电子商务专业教学标准", "电子商务"),
        # #2 / #3 — clean extractor output already "电子商务". Idempotent.
        ("电子商务", "电子商务"),
        # #4 — 专业简介 title strips the type suffix; extractor may
        # return "电子商务类"; class-suffix strip normalizes to
        # "电子商务" so it lives on the same major_name row as #1-#3.
        ("电子商务类", "电子商务"),
        # #5 — no code, same normalization as #2. Documented for
        # completeness even though it's the same input.
        ("电子商务", "电子商务"),
        # #6/#7 — 跨境电商 / 跨境电子商务 stripped of their
        # 教学标准 suffix. Ensures the long-suffix strip works cleanly.
        ("跨境电商专业教学标准", "跨境电商"),
        ("跨境电子商务专业教学标准", "跨境电子商务"),
        # #8 — must PRESERVE "大类" (compound word), even if suffix
        # is "教学标准" (that gets stripped, class-strip is what has
        # to be careful).
        ("财经商贸大类教学标准", "财经商贸大类"),
        # #9 — empty / whitespace → None.
        ("", None),
        ("   ", None),
        # #10 — parenthesized qualifier stays intact; "教学标准（2024 修订）"
        # is NOT part of the asset-type list so the parenthetical is
        # preserved, but "教学标准" alone gets stripped.
        (
            "电子商务（跨境方向）专业教学标准",
            "电子商务（跨境方向）",
        ),
        # #11 — the standalone "电子商务类" sample from the task package
        #归一化不变量 assertion — same result as #4.
        ("电子商务类", "电子商务"),
    ],
)
def test_normalize_major_name_golden_samples(raw, expected):
    assert normalize_major_name(raw) == expected


# ---------------------------------------------------------------------------
# 归一化不变量：#4 (电子商务类) and #1 (电子商务专业教学标准) collapse to
# the same normalized value so the /by-major substring query hits both.
# ---------------------------------------------------------------------------


def test_normalize_invariant_class_and_standard_collapse_to_same_name():
    assert normalize_major_name("电子商务类") == normalize_major_name(
        "电子商务专业教学标准"
    )


# ---------------------------------------------------------------------------
# Suffix-stripping ordering
# ---------------------------------------------------------------------------


def test_longer_suffix_matched_before_shorter():
    """Guard against alternation ordering — "职业教育专业教学标准" must
    be stripped whole rather than leaving "职业教育专业" after the
    shorter "教学标准" strip fires first."""
    assert (
        normalize_major_name("电子商务职业教育专业教学标准") == "电子商务"
    )


def test_ability_analysis_suffix_stripped():
    assert normalize_major_name("电子商务职业能力分析表") == "电子商务"
    assert normalize_major_name("电子商务能力分析表") == "电子商务"


def test_major_profile_suffix_stripped():
    assert normalize_major_name("电子商务专业简介") == "电子商务"
    assert normalize_major_name("电子商务院校专业简介") == "电子商务"


# ---------------------------------------------------------------------------
# 大类 preservation edge cases
# ---------------------------------------------------------------------------


def test_da_lei_preserved_when_no_asset_suffix():
    assert normalize_major_name("财经商贸大类") == "财经商贸大类"


def test_da_lei_preserved_with_asset_suffix():
    assert normalize_major_name("财经商贸大类教学标准") == "财经商贸大类"


def test_ye_lei_still_stripped():
    """The lookbehind only guards "大类" — other compound "X类" forms
    still get stripped since business decisions don't distinguish
    (see task package §1.13 归一化规则)."""
    assert normalize_major_name("电子商务类") == "电子商务"
    # An A-level "类" that's not "大类" also strips: this is a plain
    # trailing "类".
    assert normalize_major_name("专业类") == "专业"


# ---------------------------------------------------------------------------
# Idempotency + whitespace handling
# ---------------------------------------------------------------------------


def test_idempotent_on_already_clean_input():
    once = normalize_major_name("电子商务专业教学标准")
    twice = normalize_major_name(once or "")
    assert once == twice == "电子商务"


def test_whitespace_trimmed_before_and_after():
    assert normalize_major_name("  电子商务专业教学标准  ") == "电子商务"


def test_returns_none_for_none_input():
    assert normalize_major_name(None) is None


def test_returns_none_when_stripping_leaves_empty_string():
    # Pathological: title is *only* an asset-type suffix. Better to
    # store NULL in build.major_name than an empty substring that
    # would match every query.
    assert normalize_major_name("专业教学标准") is None
    assert normalize_major_name("教学标准") is None


# ---------------------------------------------------------------------------
# normalize_major_code — light validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    ("5307", "5307"),
    ("530701", "530701"),
    (" 530701 ", "530701"),
    ("", None),
    ("   ", None),
    (None, None),
    ("abc", None),
    ("123", None),          # too short
    ("1234567", None),      # too long
    ("530-701", None),      # contains non-digit
])
def test_normalize_major_code(raw, expected):
    assert normalize_major_code(raw) == expected
