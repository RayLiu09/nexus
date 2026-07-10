"""Coverage guards for `nexus_app.retrieval.display_labels`.

These tests intentionally freeze the invariant that **every** enum value the
frontend can see resolves to a Chinese label — a new tag_type / domain /
channel / status added upstream must fail here before it ships, forcing
whoever added the code to also add the label.
"""

from __future__ import annotations

import pytest

from nexus_app.ai_governance.tag_taxonomy import TAG_TAXONOMY_V1_3
from nexus_app.retrieval.display_labels import (
    CHANNEL_DISPLAY_LABELS,
    MATCH_LAYER_DISPLAY_LABELS,
    PURPOSE_DISPLAY_LABELS,
    STATUS_DISPLAY_LABELS,
    DisplayLabelError,
    format_match_layer_summary,
    format_match_strategy_display,
    get_channel_display_label,
    get_domain_display_label,
    get_match_layer_display_label,
    get_purpose_display_label,
    get_status_display_label,
    get_tag_type_display_label,
    snapshot,
)
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    StepStatus,
)


class TestTagTypeCoverage:
    def test_every_tag_taxonomy_code_has_label(self) -> None:
        """The 7 codes in TAG_TAXONOMY_V1_3 must all resolve to a name."""
        for entry in TAG_TAXONOMY_V1_3["types"]:
            code = entry["code"]
            label = get_tag_type_display_label(code)
            assert label == entry["name"]
            assert label  # non-empty

    def test_unknown_code_raises_without_fallback(self) -> None:
        with pytest.raises(DisplayLabelError):
            get_tag_type_display_label("unknown_tag_type")

    def test_fallback_returned_when_supplied(self) -> None:
        assert get_tag_type_display_label("unknown", fallback="X") == "X"


class TestDomainCoverage:
    def test_every_business_domain_has_label(self) -> None:
        """Every enum member in BusinessDomain must map to a display name."""
        for domain in BusinessDomain:
            label = get_domain_display_label(domain.value)
            assert label
            # sanity: expected Chinese labels are non-ASCII
            assert any("\u4e00" <= c <= "\u9fff" for c in label), (
                f"expected Chinese label for {domain.value!r}, got {label!r}"
            )

    def test_unknown_domain_raises_without_fallback(self) -> None:
        with pytest.raises(DisplayLabelError):
            get_domain_display_label("does_not_exist")

    def test_fallback_returned_when_supplied(self) -> None:
        assert (
            get_domain_display_label("does_not_exist", fallback="兜底") == "兜底"
        )


class TestChannelCoverage:
    def test_every_retrieval_channel_has_label(self) -> None:
        for channel in RetrievalChannel:
            label = get_channel_display_label(channel.value)
            assert label

    def test_channel_map_matches_enum_exactly(self) -> None:
        """No extraneous keys, no missing keys.  Adding a new RetrievalChannel
        upstream must not silently leave the map inconsistent."""
        assert set(CHANNEL_DISPLAY_LABELS.keys()) == {c.value for c in RetrievalChannel}

    def test_unknown_channel_raises(self) -> None:
        with pytest.raises(DisplayLabelError):
            get_channel_display_label("telepathic")


class TestPurposeCoverage:
    def test_purpose_map_contains_v1_3_examples(self) -> None:
        # v1.3 §5.3 example plan uses these purposes.
        for purpose in (
            "background_evidence",
            "trend_evidence",
            "aggregation",
            "ability_expansion",
            "supply_side",
            "curriculum_support",
        ):
            assert purpose in PURPOSE_DISPLAY_LABELS

    def test_unknown_purpose_falls_back_softly(self) -> None:
        """Purpose vocabulary is open — we tolerate unknown codes."""
        assert get_purpose_display_label("weird_new_purpose") == "weird new purpose"
        assert get_purpose_display_label("") == "（未标注目的）"

    def test_explicit_fallback_beats_soft_default(self) -> None:
        assert (
            get_purpose_display_label("weird_new_purpose", fallback="X") == "X"
        )


class TestMatchLayerCoverage:
    def test_layers_covered_at_least_up_to_l5(self) -> None:
        for code in ("L1", "L1.5", "L2", "L3", "L4", "L5"):
            assert get_match_layer_display_label(code)

    def test_lowercase_input_normalised(self) -> None:
        assert get_match_layer_display_label("l1") == "精确匹配"
        assert get_match_layer_display_label("l1.5") == "归一化匹配"

    def test_unknown_layer_raises(self) -> None:
        with pytest.raises(DisplayLabelError):
            get_match_layer_display_label("L99")

    def test_map_contents_are_chinese(self) -> None:
        for value in MATCH_LAYER_DISPLAY_LABELS.values():
            assert any("\u4e00" <= c <= "\u9fff" for c in value)


class TestFormatMatchLayerSummary:
    def test_typical_l1_l1_5_l4_distribution(self) -> None:
        result = format_match_layer_summary({"L1": 60, "L1.5": 25, "L4": 15})
        assert result == "精确匹配 60% / 归一化匹配 25% / 语义匹配 15%"

    def test_zero_count_layers_omitted(self) -> None:
        result = format_match_layer_summary({"L1": 100, "L4": 0})
        assert result == "精确匹配 100%"

    def test_ratios_accepted_and_normalised(self) -> None:
        result = format_match_layer_summary({"L1": 0.6, "L1.5": 0.25, "L4": 0.15})
        assert result == "精确匹配 60% / 归一化匹配 25% / 语义匹配 15%"

    def test_empty_input_returns_empty(self) -> None:
        assert format_match_layer_summary({}) == ""
        assert format_match_layer_summary({"L1": 0}) == ""

    def test_layer_order_is_canonical(self) -> None:
        # Even if L4 comes first in the dict, output must go L1 → L1.5 → L4
        result = format_match_layer_summary(
            {"L4": 30, "L1": 50, "L1.5": 20}
        )
        assert result.index("精确匹配") < result.index("归一化匹配") < result.index("语义匹配")


class TestFormatMatchStrategyDisplay:
    def test_l1_only(self) -> None:
        assert format_match_strategy_display("l1") == "精确匹配"

    def test_l1_l1_5_still_treated_as_精确(self) -> None:
        assert format_match_strategy_display("l1|l1.5") == "精确匹配"

    def test_l4_only(self) -> None:
        assert format_match_strategy_display("l4") == "语义匹配"

    def test_l1_l1_5_l4_returns_精确或语义(self) -> None:
        assert format_match_strategy_display("l1|l1.5|l4") == "精确或语义匹配"

    def test_empty_falls_back_to_conservative_phrase(self) -> None:
        assert format_match_strategy_display("") == "精确或语义匹配"


class TestStatusCoverage:
    def test_every_step_status_has_label(self) -> None:
        for status in StepStatus:
            assert get_status_display_label(status.value)

    def test_status_map_covers_step_status_enum(self) -> None:
        expected = {s.value for s in StepStatus}
        # Our map may carry extra sub_query_card statuses (e.g. 'degraded'),
        # but must at minimum cover every StepStatus.
        assert expected.issubset(set(STATUS_DISPLAY_LABELS.keys())), (
            f"missing status labels: {expected - set(STATUS_DISPLAY_LABELS.keys())}"
        )

    def test_degraded_covered(self) -> None:
        """`degraded` is added by SubQueryCard.status but not by StepStatus."""
        assert get_status_display_label("degraded") == "已完成（部分降级）"

    def test_unknown_status_raises_without_fallback(self) -> None:
        with pytest.raises(DisplayLabelError):
            get_status_display_label("suspended")


class TestSnapshot:
    def test_snapshot_returns_all_axes(self) -> None:
        snap = snapshot()
        assert set(snap.keys()) == {
            "tag_types", "domains", "channels", "purposes",
            "match_layers", "statuses",
        }
        assert len(snap["tag_types"]) == 7
        assert set(snap["channels"].keys()) == {c.value for c in RetrievalChannel}
