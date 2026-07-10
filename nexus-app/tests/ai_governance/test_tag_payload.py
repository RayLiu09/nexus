"""Unit tests for v1.3 A2 governance_result.tags dual-read.

Covers ``nexus_app.ai_governance.tag_payload`` and the derived
``GovernanceResultRead.tags_structured`` view.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from nexus_app.ai_governance.tag_payload import (
    STRUCTURED_TAG_CATEGORIES,
    STRUCTURED_TAG_CATEGORY_CODES,
    StructuredTagBag,
    TagValue,
    TimeRangeValue,
    detect_tags_shape,
    empty_structured_tag_bag,
    flatten_to_legacy,
    normalize_to_structured,
)


class TestShapeDetection:
    def test_none_is_empty(self) -> None:
        assert detect_tags_shape(None) == "empty"

    def test_empty_list_is_empty(self) -> None:
        assert detect_tags_shape([]) == "empty"

    def test_empty_dict_is_empty(self) -> None:
        assert detect_tags_shape({}) == "empty"

    def test_list_of_str_is_flat(self) -> None:
        assert detect_tags_shape(["直播电商", "北京市"]) == "flat"

    def test_dict_with_bucket_keys_is_structured(self) -> None:
        payload = {"regions": [], "industries": []}
        assert detect_tags_shape(payload) == "structured"

    def test_dict_without_bucket_keys_is_unknown(self) -> None:
        assert detect_tags_shape({"foo": 1}) == "unknown"

    def test_mixed_list_is_unknown(self) -> None:
        assert detect_tags_shape(["直播电商", {"value": "北京市"}]) == "unknown"


class TestTagValue:
    def test_confidence_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TagValue(value="x", confidence=1.5)

    def test_empty_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TagValue(value="")

    def test_optional_fields_default_to_none(self) -> None:
        tv = TagValue(value="直播电商")
        assert tv.confidence is None
        assert tv.evidence_span is None


class TestStructuredTagBag:
    def test_empty_bag_has_all_seven_buckets(self) -> None:
        bag = empty_structured_tag_bag()
        for cat in STRUCTURED_TAG_CATEGORY_CODES:
            assert getattr(bag, cat) == []

    def test_duplicate_values_within_category_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StructuredTagBag(
                industries=[TagValue(value="x"), TagValue(value="x")]
            )

    def test_duplicate_values_across_categories_allowed(self) -> None:
        # A value can legitimately appear in region and topic buckets, for
        # example "北京" as a place name might also carry topic weight.
        bag = StructuredTagBag(
            regions=[TagValue(value="北京")],
            topics=[TagValue(value="北京")],
        )
        assert bag.regions[0].value == "北京"
        assert bag.topics[0].value == "北京"

    def test_taxonomy_type_codes_map_to_bucket_names(self) -> None:
        """The seven singular tag_taxonomy codes must map onto the seven
        plural bucket names used in the structured payload."""
        from nexus_app.ai_governance.tag_taxonomy import TAG_TAXONOMY_V1_3

        taxonomy_codes = {t["code"] for t in TAG_TAXONOMY_V1_3["types"]}
        assert taxonomy_codes == set(STRUCTURED_TAG_CATEGORIES.keys())
        assert set(STRUCTURED_TAG_CATEGORIES.values()) == set(
            STRUCTURED_TAG_CATEGORY_CODES
        )


class TestNormalize:
    def test_flat_strings_land_in_topics(self) -> None:
        bag = normalize_to_structured(["直播电商", "北京市"])
        assert [tv.value for tv in bag.topics] == ["直播电商", "北京市"]
        assert bag.regions == []
        # confidence + evidence remain None for up-cast legacy tags
        for tv in bag.topics:
            assert tv.confidence is None
            assert tv.evidence_span is None

    def test_flat_strings_deduplicated_preserving_order(self) -> None:
        bag = normalize_to_structured(["直播电商", "直播电商", "北京市"])
        assert [tv.value for tv in bag.topics] == ["直播电商", "北京市"]

    def test_flat_strings_ignore_blanks(self) -> None:
        bag = normalize_to_structured(["直播电商", "   ", ""])
        assert [tv.value for tv in bag.topics] == ["直播电商"]

    def test_empty_returns_empty_bag(self) -> None:
        assert normalize_to_structured(None).model_dump() == empty_structured_tag_bag().model_dump()
        assert normalize_to_structured([]).model_dump() == empty_structured_tag_bag().model_dump()
        assert normalize_to_structured({}).model_dump() == empty_structured_tag_bag().model_dump()

    def test_structured_dict_passes_through_validation(self) -> None:
        raw = {
            "regions": [{"value": "北京市", "confidence": 0.95, "evidence_span": "…"}],
            "industries": [{"value": "直播电商"}],
        }
        bag = normalize_to_structured(raw)
        assert bag.regions[0].value == "北京市"
        assert bag.regions[0].confidence == 0.95
        assert bag.industries[0].value == "直播电商"

    def test_unknown_shape_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_to_structured("some string")

    def test_unknown_dict_shape_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_to_structured({"foo": [1, 2]})


class TestFlattenBack:
    def test_flat_list_dedup(self) -> None:
        assert flatten_to_legacy(["a", "b", "a"]) == ["a", "b"]

    def test_bag_flattens_in_canonical_order(self) -> None:
        bag = StructuredTagBag(
            time_ranges=[TimeRangeValue(kind="point_in_time", year=2025)],
            regions=[TagValue(value="北京市")],
            industries=[TagValue(value="直播电商")],
        )
        assert flatten_to_legacy(bag) == ["北京市", "直播电商", "2025"]

    def test_bag_dedup_across_buckets(self) -> None:
        bag = StructuredTagBag(
            regions=[TagValue(value="北京")],
            topics=[TagValue(value="北京")],
        )
        assert flatten_to_legacy(bag) == ["北京"]

    def test_dict_input_supported(self) -> None:
        result = flatten_to_legacy({"industries": [{"value": "直播电商"}]})
        assert result == ["直播电商"]

    def test_dict_input_tolerates_dirty_items(self) -> None:
        """Dirty items (empty value, missing key, wrong type) must be silently
        skipped so a single garbage LLM output doesn't short-circuit the
        surrounding sanitiser (see decision_service._extract_governance_tags).
        """
        payload = {
            "regions": [
                {"value": "北京市"},
                {"value": ""},          # empty string
                {"confidence": 0.9},    # no value key
                42,                     # wrong item type
            ],
            "industries": [{"value": "  直播电商  "}],  # gets stripped
            "unknown_bucket": [{"value": "ignored"}],   # non-canonical bucket
        }
        assert flatten_to_legacy(payload) == ["北京市", "直播电商"]

    def test_dict_input_ignores_non_list_buckets(self) -> None:
        payload = {"regions": "not a list", "topics": [{"value": "x"}]}
        assert flatten_to_legacy(payload) == ["x"]

    def test_unknown_scalar_returns_empty(self) -> None:
        # A completely unrecognised type must not raise — just return [].
        assert flatten_to_legacy(42) == []  # type: ignore[arg-type]


class TestGovernanceResultReadDualView:
    """The ``GovernanceResultRead`` schema must expose a normalised
    ``tags_structured`` bag regardless of what shape ``tags`` was stored in.
    """

    def _base_payload(self, tags):
        # Minimal legal fields for a governance_result row + timestamps.
        now = datetime.now(timezone.utc)
        return {
            "id": "r1",
            "normalized_ref_id": "n1",
            "ai_run_id": None,
            "classification": "industry_policy",
            "level": "L2",
            "tags": tags,
            "org_scope": None,
            "index_admission": True,
            "quality_summary": None,
            "decision_trail": [],
            "rules_schema_version": "3.0",
            "rules_content_hash": None,
            "status": "available",
            "created_by": None,
            "trace_id": None,
            "created_at": now,
            "updated_at": now,
        }

    def test_flat_tags_produce_topics_bucket(self) -> None:
        from nexus_app.schemas import GovernanceResultRead

        payload = self._base_payload(["直播电商", "北京市"])
        read = GovernanceResultRead.model_validate(payload)
        assert read.tags_shape == "flat"
        assert [t["value"] for t in read.tags_structured["topics"]] == [
            "直播电商", "北京市",
        ]
        assert read.tags_structured["regions"] == []

    def test_structured_tags_passthrough(self) -> None:
        from nexus_app.schemas import GovernanceResultRead

        payload = self._base_payload(
            {
                "regions": [{"value": "北京市", "confidence": 0.95}],
                "industries": [{"value": "直播电商"}],
            }
        )
        read = GovernanceResultRead.model_validate(payload)
        assert read.tags_shape == "structured"
        assert read.tags_structured["regions"][0]["value"] == "北京市"
        assert read.tags_structured["regions"][0]["confidence"] == 0.95
        assert read.tags_structured["industries"][0]["value"] == "直播电商"

    def test_empty_tags_yields_empty_bag(self) -> None:
        from nexus_app.schemas import GovernanceResultRead

        payload = self._base_payload([])
        read = GovernanceResultRead.model_validate(payload)
        assert read.tags_shape == "empty"
        # All seven buckets present, all empty
        for cat in STRUCTURED_TAG_CATEGORY_CODES:
            assert read.tags_structured[cat] == []
