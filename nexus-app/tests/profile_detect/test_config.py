"""Tests for `profile_detect.config` detector rules.

Pins:
  - PGSD code regex matches sample 2 codes (P-1.1.1 three-segment, G/S/D-1.1
    two-segment)
  - PGSD sheet-name regex matches sample 2 sub-sheet names
  - Alias sets are non-empty and immutable (frozenset)
  - Detector version follows the required `record-profile-detector.*` format
"""
from __future__ import annotations

import pytest

from nexus_app.profile_detect.config import (
    DEFAULT_AUTO_ADMIT_THRESHOLD,
    DETECTOR_VERSION,
    JOB_DEMAND_HEADER_ALIASES,
    JOB_DEMAND_OPTIONAL_HEADERS,
    OVERVIEW_SHEET_KEYWORDS,
    PGSD_CATEGORY_ALIASES,
    PGSD_CODE_PREFIX_PATTERN,
    PGSD_REQUIRED_CATEGORIES,
    PGSD_SHEET_NAME_PATTERN,
)


# ---------------------------------------------------------------------------
# Version + threshold
# ---------------------------------------------------------------------------


class TestDetectorVersion:
    def test_version_string_format(self):
        # Contract-freeze §二 requires `record-profile-detector.<semver-like>`.
        assert DETECTOR_VERSION.startswith("record-profile-detector.")
        # No trailing whitespace / newline (caught early — would corrupt audits)
        assert DETECTOR_VERSION == DETECTOR_VERSION.strip()

    def test_default_threshold_in_range(self):
        assert 0.0 < DEFAULT_AUTO_ADMIT_THRESHOLD <= 1.0
        # 0.85 is the documented default in implementation plan §三
        assert DEFAULT_AUTO_ADMIT_THRESHOLD == 0.85


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestCollectionsAreImmutable:
    @pytest.mark.parametrize(
        "collection",
        [
            JOB_DEMAND_HEADER_ALIASES,
            JOB_DEMAND_OPTIONAL_HEADERS,
            PGSD_REQUIRED_CATEGORIES,
            OVERVIEW_SHEET_KEYWORDS,
        ],
    )
    def test_collection_is_frozenset(self, collection):
        # frozenset is critical: a module-level set could be mutated by
        # a test and silently leak into the next test run.
        assert isinstance(collection, frozenset)

    @pytest.mark.parametrize(
        "collection",
        [
            JOB_DEMAND_HEADER_ALIASES,
            JOB_DEMAND_OPTIONAL_HEADERS,
            PGSD_REQUIRED_CATEGORIES,
            OVERVIEW_SHEET_KEYWORDS,
        ],
    )
    def test_collection_non_empty(self, collection):
        assert len(collection) > 0


# ---------------------------------------------------------------------------
# Job demand aliases — must cover sample 1 headers
# ---------------------------------------------------------------------------


class TestJobDemandAliases:
    @pytest.mark.parametrize("header", ["岗位名称", "城市", "公司名称"])
    def test_sample1_core_headers_are_required_aliases(self, header):
        assert header in JOB_DEMAND_HEADER_ALIASES

    @pytest.mark.parametrize(
        "header",
        [
            "薪资", "经验要求", "学历要求", "岗位描述",
            "公司规模", "所属产业", "发布时间", "岗位类型",
        ],
    )
    def test_sample1_optional_headers_recognised(self, header):
        assert header in JOB_DEMAND_OPTIONAL_HEADERS

    def test_required_and_optional_disjoint(self):
        # Same header in both sets would double-count confidence in B2.2.
        overlap = JOB_DEMAND_HEADER_ALIASES & JOB_DEMAND_OPTIONAL_HEADERS
        assert overlap == set(), f"unexpected overlap: {overlap}"


# ---------------------------------------------------------------------------
# PGSD categories
# ---------------------------------------------------------------------------


class TestPgsdCategories:
    def test_four_required_categories_present(self):
        # Decision 12 / design §5.2 — PGSD profile requires all four.
        assert PGSD_REQUIRED_CATEGORIES == frozenset({
            "职业能力", "通用能力", "社会能力", "发展能力",
        })

    def test_zhiye_jineng_aliases_to_zhiye_nengli(self):
        # Decision 1 (settled design §十二): "职业技能" is an ALIAS of "职业能力"
        # (canonical display name). The detector must normalise this so
        # legacy ability-analysis tables still match.
        assert PGSD_CATEGORY_ALIASES["职业技能"] == "职业能力"


# ---------------------------------------------------------------------------
# PGSD ability-code regex — must match all 4 prefix variants in sample 2
# ---------------------------------------------------------------------------


class TestPgsdCodeRegex:
    @pytest.mark.parametrize(
        "code",
        [
            "P-1.1.1",   # 职业能力 (P) — three-segment, sample 2
            "P-3.4.4",
            "G-1.1",     # 通用能力 (G) — two-segment, sample 2
            "G-2.3",
            "S-1.1",     # 社会能力 (S)
            "S-4.3",
            "D-1.1",     # 发展能力 (D)
            "D-2.2",
        ],
    )
    def test_canonical_codes_match(self, code):
        assert PGSD_CODE_PREFIX_PATTERN.match(code), (
            f"sample-2 ability code {code!r} should match PGSD_CODE_PREFIX_PATTERN"
        )

    @pytest.mark.parametrize(
        "non_code",
        [
            "P",           # bare prefix without segments
            "P-",          # trailing dash, no digits
            "P-1",         # one-segment only — sample 2 doesn't use this
            "X-1.1",       # unknown category letter
            "p-1.1.1",     # lowercase rejected (design pins P/G/S/D uppercase)
            " P-1.1.1",    # leading whitespace rejected — detectors strip before match
            "P-1.1.1 ",    # trailing whitespace rejected
            "P-1.1.1.1",   # four-segment is out of spec
        ],
    )
    def test_non_canonical_codes_rejected(self, non_code):
        assert PGSD_CODE_PREFIX_PATTERN.match(non_code) is None, (
            f"{non_code!r} should NOT match — detector would mis-classify"
        )


# ---------------------------------------------------------------------------
# PGSD sheet-name regex — sample 2's per-task sheets
# ---------------------------------------------------------------------------


class TestPgsdSheetNamePattern:
    @pytest.mark.parametrize(
        "name",
        [
            "1.数据采集",
            "2.数据标注",
            "3.数据ETL处理",
            "4.可视化图表制作",
            "10.高位编号也匹配",   # detector must not pin sheets to single-digit prefix
        ],
    )
    def test_sample2_sheet_names_match(self, name):
        assert PGSD_SHEET_NAME_PATTERN.match(name)

    @pytest.mark.parametrize(
        "name",
        [
            "Sheet1",                    # sample 1 — should NOT match
            "典型工作任务和工作内容分析表",  # overview sheet has no digit prefix
            "data_collection",           # no Chinese chars after dot
            "1 数据采集",                 # space instead of dot
            ".数据采集",                  # missing digit
        ],
    )
    def test_non_canonical_sheet_names_rejected(self, name):
        assert PGSD_SHEET_NAME_PATTERN.match(name) is None


# ---------------------------------------------------------------------------
# Overview sheet keywords
# ---------------------------------------------------------------------------


class TestOverviewSheetKeywords:
    def test_typical_overview_token_present(self):
        # Sample 2's overview sheet is named "典型工作任务和工作内容分析表".
        # The detector matches if ANY keyword appears as substring.
        assert any(
            kw in "典型工作任务和工作内容分析表" for kw in OVERVIEW_SHEET_KEYWORDS
        )
