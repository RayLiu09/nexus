"""PR-2 guards for v1.3 tag_filter + friendly_view Pydantic contract.

Ensures:

* The literal type aliases match every downstream single-source
  invariant (I-2: tag_type codes; I-3: singular↔plural mapping).
* TagFilter / BindingSpec reject malformed match_strategy / source
  expressions at parse time — the resolver never has to defend against
  drift.
* CrossAssetTags / TimeRangeCandidate structural shape mirrors
  ``tag_payload.StructuredTagBag`` so serialisation round-trips work
  between the storage and retrieval sides.
* Every friendly_view sub-model rejects empty / negative fields per
  v1.3 §5.5 contract.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus_app.ai_governance.tag_payload import STRUCTURED_TAG_CATEGORY_CODES
from nexus_app.ai_governance.tag_taxonomy import TAG_TAXONOMY_V1_3
from nexus_app.retrieval.tag_schemas import (
    TAG_BUCKET_NAMES,
    TAG_TYPE_CODES,
    BindingSpec,
    CrossAssetTags,
    DisplayConstraint,
    DisplayFilter,
    FriendlyRetrievalPlanView,
    IntentSummary,
    OverallSummary,
    SubQueryCard,
    SubQueryResult,
    TagCandidate,
    TagFilter,
    TimeRangeCandidate,
)


# ---------------------------------------------------------------------------
# Cross-module invariants
# ---------------------------------------------------------------------------


class TestSingleSourceInvariants:
    def test_tag_type_codes_match_tag_taxonomy(self) -> None:
        """I-2: TagTypeCode Literal must enumerate exactly the codes in
        TAG_TAXONOMY_V1_3.  A new taxonomy code must be added here at the
        same time or the schema validation goes silent."""
        taxonomy_codes = tuple(t["code"] for t in TAG_TAXONOMY_V1_3["types"])
        assert TAG_TYPE_CODES == taxonomy_codes

    def test_bucket_names_match_structured_tag_categories(self) -> None:
        """I-3: singular tag_type codes ↔ plural bucket names.  The two
        sides are enforced by the same canonical mapping (declared in
        tag_payload); we mirror the plural side here so drift surfaces
        as a test failure."""
        assert TAG_BUCKET_NAMES == STRUCTURED_TAG_CATEGORY_CODES


# ---------------------------------------------------------------------------
# TagCandidate
# ---------------------------------------------------------------------------


class TestTagCandidate:
    def test_basic_ok(self) -> None:
        tag = TagCandidate(value="北京市")
        assert tag.value == "北京市"
        assert tag.confidence is None

    def test_value_trimmed(self) -> None:
        tag = TagCandidate(value="  北京市  ")
        assert tag.value == "北京市"

    def test_reject_empty(self) -> None:
        with pytest.raises(ValidationError):
            TagCandidate(value="   ")

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TagCandidate(value="x", confidence=1.5)
        with pytest.raises(ValidationError):
            TagCandidate(value="x", confidence=-0.1)


# ---------------------------------------------------------------------------
# TimeRangeCandidate
# ---------------------------------------------------------------------------


class TestTimeRangeCandidate:
    def test_year_range_requires_start_end(self) -> None:
        with pytest.raises(ValidationError):
            TimeRangeCandidate(kind="year_range", start=2024)  # missing end

    def test_year_range_start_must_be_le_end(self) -> None:
        with pytest.raises(ValidationError):
            TimeRangeCandidate(kind="year_range", start=2025, end=2024)

    def test_point_in_time_requires_year(self) -> None:
        with pytest.raises(ValidationError):
            TimeRangeCandidate(kind="point_in_time")

    def test_valid_shapes(self) -> None:
        assert TimeRangeCandidate(kind="year_range", start=2024, end=2026).end == 2026
        assert TimeRangeCandidate(kind="point_in_time", year=2025).year == 2025


# ---------------------------------------------------------------------------
# CrossAssetTags
# ---------------------------------------------------------------------------


class TestCrossAssetTags:
    def test_empty_bag_valid(self) -> None:
        bag = CrossAssetTags()
        assert bag.is_empty()

    def test_all_seven_buckets_present(self) -> None:
        bag = CrossAssetTags()
        for bucket in TAG_BUCKET_NAMES:
            assert getattr(bag, bucket) == []

    def test_populated_bag_not_empty(self) -> None:
        bag = CrossAssetTags(regions=[TagCandidate(value="北京市")])
        assert not bag.is_empty()


# ---------------------------------------------------------------------------
# TagFilter
# ---------------------------------------------------------------------------


class TestTagFilterMatchStrategy:
    def test_default_is_l1_l1_5_l4(self) -> None:
        tf = TagFilter(tags=["直播电商"])
        assert tf.match_strategy == "l1|l1.5|l4"

    def test_canonicalises_case(self) -> None:
        tf = TagFilter(tags=["直播电商"], match_strategy="L1 | L1.5")
        assert tf.match_strategy == "l1|l1.5"

    def test_reject_unknown_layer(self) -> None:
        with pytest.raises(ValidationError, match="unknown layer"):
            TagFilter(tags=["x"], match_strategy="l1|l99")

    def test_reject_empty_token(self) -> None:
        with pytest.raises(ValidationError, match="empty layer token"):
            TagFilter(tags=["x"], match_strategy="l1||l4")


class TestTagFilterTags:
    def test_list_of_strings_ok(self) -> None:
        tf = TagFilter(tags=["直播电商", "跨境电商"])
        assert tf.tags == ["直播电商", "跨境电商"]

    def test_list_entries_trimmed(self) -> None:
        tf = TagFilter(tags=["  直播电商  "])
        assert tf.tags == ["直播电商"]

    def test_empty_string_in_list_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TagFilter(tags=["直播电商", "   "])

    def test_binding_expression_ok(self) -> None:
        tf = TagFilter(tags="$shared.industries")
        assert tf.tags == "$shared.industries"

    def test_binding_expression_must_start_with_dollar(self) -> None:
        with pytest.raises(ValidationError, match="must start with"):
            TagFilter(tags="shared.industries")

    def test_binding_expression_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            TagFilter(tags="  ")

    def test_optional_flag(self) -> None:
        tf = TagFilter(tags=["x"], optional=True)
        assert tf.optional is True


class TestTagFilterBounds:
    def test_semantic_threshold_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TagFilter(tags=["x"], semantic_threshold=1.2)

    def test_top_k_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TagFilter(tags=["x"], top_k=0)


# ---------------------------------------------------------------------------
# BindingSpec
# ---------------------------------------------------------------------------


class TestBindingSpec:
    def test_basic_ok(self) -> None:
        b = BindingSpec(
            source="$q_job.output.top_jobs[*].job_title",
            as_tag_type="occupation",
        )
        assert b.source.startswith("$q_job")
        assert b.as_tag_type == "occupation"

    def test_source_must_start_with_dollar(self) -> None:
        with pytest.raises(ValidationError, match="must start with"):
            BindingSpec(source="q_job.output", as_tag_type="occupation")

    def test_source_needs_field_reference(self) -> None:
        with pytest.raises(ValidationError, match="must reference"):
            BindingSpec(source="$q_job", as_tag_type="occupation")

    def test_as_tag_type_must_be_valid_taxonomy_code(self) -> None:
        with pytest.raises(ValidationError):
            BindingSpec(
                source="$q_job.output.x",
                as_tag_type="fictional_type",
            )


# ---------------------------------------------------------------------------
# friendly_view sub-models
# ---------------------------------------------------------------------------


class TestFriendlyView:
    def _minimal_intent_summary(self) -> IntentSummary:
        return IntentSummary(
            natural_language="查询北京市直播电商产业规划",
            business_domains_display=["产业政策"],
            confidence=0.86,
            confidence_level="high",
        )

    def _minimal_overall(self) -> OverallSummary:
        return OverallSummary(
            total_sub_queries=5,
            max_depth=3,
            combine_summary="所有维度均需匹配（AND）",
        )

    def test_minimal_view(self) -> None:
        view = FriendlyRetrievalPlanView(
            intent_summary=self._minimal_intent_summary(),
            overall=self._minimal_overall(),
        )
        assert view.sub_query_cards == []

    def test_display_constraint_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            DisplayConstraint(label="", value="北京市", source_display="从问题中识别")
        with pytest.raises(ValidationError):
            DisplayConstraint(label="地区", value="", source_display="从问题中识别")

    def test_display_filter_default_optional_false(self) -> None:
        df = DisplayFilter(
            label="地区",
            values=["北京市"],
            match_strategy_display="精确匹配",
        )
        assert df.is_optional is False
        assert df.is_from_binding is None

    def test_sub_query_result_rejects_negative_hit_count(self) -> None:
        with pytest.raises(ValidationError):
            SubQueryResult(
                hit_count=-1,
                hit_count_display="-1",
                duration_ms=100,
                duration_display="100 ms",
                evidence_strength="strong",
                evidence_strength_display="证据强度：强",
            )

    def test_sub_query_card_status_literal(self) -> None:
        # Valid literal
        card = SubQueryCard(
            query_id="q_job",
            display_index="②",
            title="分析北京市直播电商岗位需求",
            purpose_display="岗位需求分析",
            channel_display="结构化数据",
            domain_display="岗位需求",
            status="running",
            status_display="执行中",
        )
        assert card.status == "running"

        # Invalid literal
        with pytest.raises(ValidationError):
            SubQueryCard(
                query_id="q_job",
                display_index="②",
                title="x",
                purpose_display="y",
                channel_display="z",
                domain_display="w",
                status="fictional",
                status_display="虚构",
            )

    def test_sub_query_card_actions_literal(self) -> None:
        card = SubQueryCard(
            query_id="q",
            display_index="①",
            title="x",
            purpose_display="y",
            channel_display="z",
            domain_display="w",
            status="completed",
            status_display="已完成",
            actions_available=["view_details", "rerun"],
        )
        assert "view_details" in card.actions_available

    def test_overall_estimated_duration_optional(self) -> None:
        o = OverallSummary(
            total_sub_queries=0,
            max_depth=0,
            combine_summary="—",
        )
        assert o.estimated_duration_ms is None

    def test_intent_summary_confidence_level_literal(self) -> None:
        with pytest.raises(ValidationError):
            IntentSummary(
                natural_language="x",
                confidence=0.5,
                confidence_level="fictional",
            )
