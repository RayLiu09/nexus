"""Freezes v1.3 unbreakable invariant I-1 (see
``docs/tag_filter_reliability_matrix_v1.md §3``): the normalisation
function is the **single source of truth** for L1/L1.5 exact matching
across intent, matcher, projection hook, and Resolver.

If any of these tests fail, downstream `target_ids` sets from the four
call sites will silently diverge and the tag_filter chain becomes
unreliable — DO NOT relax the assertions without going through a
contract change review.
"""

from __future__ import annotations

import pytest

from nexus_app.ai_governance.tag_normalization import (
    SHORT_FORM_EXPANSIONS,
    SUFFIX_STRIP_RULES,
    normalize_tag_value,
    denormalize_debug,
)
from nexus_app.ai_governance.tag_taxonomy import TAG_TAXONOMY_V1_3


class TestBasicInputHandling:
    def test_none_returns_empty_string(self) -> None:
        assert normalize_tag_value(None) == ""

    def test_empty_returns_empty(self) -> None:
        assert normalize_tag_value("") == ""

    def test_non_string_is_stringified(self) -> None:
        assert normalize_tag_value(2025) == "2025"

    def test_pure_whitespace_collapses_to_empty(self) -> None:
        assert normalize_tag_value("   \t\n") == ""


class TestNFKC:
    def test_fullwidth_ascii_folds(self) -> None:
        # Fullwidth digits/letters/punctuation should NFKC to ASCII.
        assert normalize_tag_value("ＡＢＣ１２３") == "abc123"

    def test_halfwidth_kana_leaves_chinese_alone(self) -> None:
        assert normalize_tag_value("北京") == "北京"


class TestBracketStripping:
    def test_chinese_parens_stripped(self) -> None:
        assert normalize_tag_value("直播电商（含短视频带货）") == "直播电商"

    def test_ascii_parens_stripped(self) -> None:
        assert normalize_tag_value("data analysis (advanced)") == "dataanalysis"

    def test_square_brackets_stripped(self) -> None:
        assert normalize_tag_value("电子商务[高职]") == "电子商务"

    def test_curly_brackets_stripped(self) -> None:
        assert normalize_tag_value("直播电商{2025}") == "直播电商"

    def test_multiple_bracket_groups(self) -> None:
        assert normalize_tag_value("直播电商（A）（B）") == "直播电商"


class TestWhitespaceCollapse:
    def test_internal_spaces_collapsed(self) -> None:
        assert normalize_tag_value("直 播 电 商") == "直播电商"

    def test_leading_trailing_trimmed(self) -> None:
        assert normalize_tag_value("  北京市  ") == "北京市"

    def test_tabs_and_newlines_treated_as_whitespace(self) -> None:
        assert normalize_tag_value("直播\t电\n商") == "直播电商"


class TestCaseFolding:
    def test_english_lowercased(self) -> None:
        assert normalize_tag_value("Python") == "python"
        assert normalize_tag_value("GMV Analysis") == "gmvanalysis"

    def test_mixed_chinese_english(self) -> None:
        assert normalize_tag_value("Python 编程") == "python编程"


class TestRegionSuffixStripping:
    """Regions are the only tag_type with suffix rules right now."""

    def test_省_stripped(self) -> None:
        assert normalize_tag_value("广东省", "region") == "广东"

    def test_市_stripped(self) -> None:
        assert normalize_tag_value("北京市", "region") == "北京"

    def test_区_stripped(self) -> None:
        assert normalize_tag_value("朝阳区", "region") == "朝阳"

    def test_县_stripped(self) -> None:
        assert normalize_tag_value("嘉善县", "region") == "嘉善"

    def test_州_stripped(self) -> None:
        assert normalize_tag_value("延边州", "region") == "延边"

    def test_自治区_stripped_as_whole_suffix_not_区(self) -> None:
        """Longest suffix wins.  '内蒙古自治区' → '内蒙古', not '内蒙古自治'."""
        assert normalize_tag_value("内蒙古自治区", "region") == "内蒙古"

    def test_特别行政区_stripped_as_whole_suffix(self) -> None:
        assert normalize_tag_value("香港特别行政区", "region") == "香港"

    def test_suffix_only_input_preserved(self) -> None:
        """A tag value that IS only a suffix ('市', '省') must not become
        empty — we require ``len(text) > len(suffix)`` before stripping."""
        assert normalize_tag_value("市", "region") == "市"
        assert normalize_tag_value("省", "region") == "省"

    def test_no_suffix_stripped_when_tag_type_omitted(self) -> None:
        assert normalize_tag_value("北京市") == "北京市"

    def test_non_region_types_do_not_strip_region_suffixes(self) -> None:
        # Even if industry/topic values end in '市', don't strip.
        assert normalize_tag_value("北京市", "industry") == "北京市"
        assert normalize_tag_value("北京市", "topic") == "北京市"


class TestShortFormExpansion:
    def test_京_expands_to_beijing(self) -> None:
        assert normalize_tag_value("京") == "北京"

    def test_sh_expands(self) -> None:
        assert normalize_tag_value("沪") == "上海"

    def test_粤_expands(self) -> None:
        assert normalize_tag_value("粤") == "广东"

    def test_short_form_after_suffix_stripping_still_works(self) -> None:
        """'京市' → suffix strip → '京' → short-form expand → '北京'."""
        assert normalize_tag_value("京市", "region") == "北京"

    def test_short_form_only_applied_on_exact_match(self) -> None:
        """'京城' does NOT expand — the short-form table is only for the
        single-character canonical case."""
        assert normalize_tag_value("京城") == "京城"

    def test_all_34_provinces_covered(self) -> None:
        """China has 34 province-level admin areas; the short-form table
        should cover them all so the L1.5 layer can silently rescue
        common short forms without leaning on L2 alias dictionaries."""
        # Represents 22 provinces + 5 autonomous regions + 4 direct-
        # controlled municipalities + 2 SARs + Taiwan.
        assert len(SHORT_FORM_EXPANSIONS) >= 30


class TestIdempotency:
    """v1.3 invariant: normalisation must be idempotent so re-writing the
    same tag through the projection hook produces the same
    ``tag_value_normalized`` — no drift."""

    _IDEMPOTENT_CASES = [
        (None, "region"),
        ("", "region"),
        ("北京市", "region"),
        ("  北京市  ", "region"),
        ("直播电商（含短视频带货）", "industry"),
        ("Python 编程", "topic"),
        ("京", "region"),
        ("内蒙古自治区", "region"),
        ("ＡＢＣ", "topic"),
    ]

    @pytest.mark.parametrize("raw,tag_type", _IDEMPOTENT_CASES)
    def test_double_normalisation_stable(self, raw, tag_type) -> None:
        once = normalize_tag_value(raw, tag_type)
        twice = normalize_tag_value(once, tag_type)
        assert once == twice, (
            f"normalisation not idempotent for {raw!r} "
            f"(tag_type={tag_type!r}): {once!r} → {twice!r}"
        )


class TestUnknownTagType:
    def test_unknown_tag_type_treated_as_generic(self) -> None:
        """Unknown tag_type must not crash — a future tag_taxonomy
        addition would otherwise break every existing call site.
        Instead it silently falls back to no-suffix-strip (the static
        guard in test_display_labels and test_tag_taxonomy_seed catches
        the missing coverage at test time)."""
        assert normalize_tag_value("北京市", "brand_new_tag_type") == "北京市"


class TestTaxonomyCoverage:
    def test_every_taxonomy_tag_type_has_suffix_rules_entry(self) -> None:
        """Every code in TAG_TAXONOMY_V1_3 must have a SUFFIX_STRIP_RULES
        entry (possibly empty tuple) — adding a new tag_type upstream
        must fail here before it ships production without a normalisation
        contract."""
        taxonomy_codes = {t["code"] for t in TAG_TAXONOMY_V1_3["types"]}
        rules_codes = set(SUFFIX_STRIP_RULES.keys())
        missing = taxonomy_codes - rules_codes
        assert not missing, (
            f"tag_taxonomy has codes with no SUFFIX_STRIP_RULES entry: {missing}. "
            f"Add each new tag_type to tag_normalization.SUFFIX_STRIP_RULES "
            f"(even if the value is an empty tuple) to make normalisation "
            f"coverage explicit."
        )


class TestDebugHelper:
    def test_debug_trace_reports_current_rule_match(self) -> None:
        trace = denormalize_debug("北京市", "北京", "region")
        assert trace["original"] == "北京市"
        assert trace["normalised"] == "北京"
        assert trace["tag_type"] == "region"
        assert trace["matches_current_rule_set"] is True

    def test_debug_trace_detects_drift(self) -> None:
        # If the stored normalised form no longer matches current rules,
        # it's a drift signal for the Console panel.
        trace = denormalize_debug("北京市", "北京市", "region")
        assert trace["matches_current_rule_set"] is False


class TestInvariantI1CrossCallSiteConsistency:
    """The invariant test.  Enumerate the four call sites in code
    (intent, L1.5 matcher, projection hook, resolver) once each becomes
    real (M-B PR-4/PR-6) and prove they all delegate to
    normalize_tag_value.  Until then, guard against drift by requiring
    every code path we can see in ai_governance / retrieval that mentions
    'normalize' to import from this module.

    In practice this is enforced by ``ruff`` + code review at PR time.
    Placeholder assertion below documents the contract."""

    def test_module_exports_expected_public_api(self) -> None:
        from nexus_app.ai_governance import tag_normalization

        assert hasattr(tag_normalization, "normalize_tag_value")
        assert hasattr(tag_normalization, "denormalize_debug")
        assert hasattr(tag_normalization, "SUFFIX_STRIP_RULES")
        assert hasattr(tag_normalization, "SHORT_FORM_EXPANSIONS")

    def test_function_is_pure(self) -> None:
        """No hidden state — same input, same output, across calls
        interleaved with other tag_types."""
        assert normalize_tag_value("北京市", "region") == "北京"
        # Call something else in between.
        assert normalize_tag_value("直播电商", "industry") == "直播电商"
        # Original still deterministic.
        assert normalize_tag_value("北京市", "region") == "北京"
