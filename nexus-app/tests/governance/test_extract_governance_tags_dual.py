"""Regression tests for _extract_governance_tags dual-shape handling.

Covers the flat-list projection of both:
* v1.3 §4.1 **structured** payloads (fast-path via
  ``flatten_to_legacy``)
* pre-v1.3 **legacy 5-dimension** or flat payloads (recursive
  ``add_many`` path)
"""

from __future__ import annotations

from nexus_app.governance.decision_service import (
    _extract_governance_tags,
    _looks_structured_tag_bag,
)


class TestStructuredShapeDetection:
    def test_none_and_scalars_are_not_structured(self) -> None:
        assert not _looks_structured_tag_bag(None)
        assert not _looks_structured_tag_bag("直播电商")
        assert not _looks_structured_tag_bag(42)

    def test_flat_list_is_not_structured(self) -> None:
        assert not _looks_structured_tag_bag(["直播电商"])

    def test_legacy_5dim_dict_is_not_structured(self) -> None:
        legacy = {
            "professional_domain": [{"value": "直播电商"}],
            "geographic_scope": [{"value": "北京市"}],
        }
        assert not _looks_structured_tag_bag(legacy)

    def test_dict_with_any_bucket_key_is_structured(self) -> None:
        assert _looks_structured_tag_bag({"industries": []})
        assert _looks_structured_tag_bag({"regions": [{"value": "北京市"}]})
        # even one bucket present is enough
        assert _looks_structured_tag_bag({"topics": [{"value": "x"}]})


class TestStructuredFastPath:
    def test_flattens_structured_payload_preserving_canonical_order(self) -> None:
        ai_output = {
            "tags": {
                "time_ranges": [{"value": "2025"}],
                "regions": [{"value": "北京市"}],
                "industries": [{"value": "直播电商"}],
            }
        }
        assert _extract_governance_tags(ai_output) == [
            "北京市", "直播电商", "2025",
        ]

    def test_dedup_across_buckets(self) -> None:
        ai_output = {
            "tags": {
                "regions": [{"value": "北京"}],
                "topics": [{"value": "北京"}],
            }
        }
        assert _extract_governance_tags(ai_output) == ["北京"]

    def test_stripping_and_filter_still_applied_via_add(self) -> None:
        # add() enforces the legacy validity filter (no model-alias-shaped
        # strings), which must still fire even on the structured fast path.
        ai_output = {
            "tags": {
                "topics": [
                    {"value": "  直播电商  "},
                    {"value": "gpt-4o-mini"},
                    {"value": ""},
                ],
                "industries": [{"value": "直播电商"}],  # duplicate after strip
            }
        }
        assert _extract_governance_tags(ai_output) == ["直播电商"]


class TestLegacyPath:
    def test_flat_list_still_supported(self) -> None:
        ai_output = {"tags": ["直播电商", "北京市"]}
        assert _extract_governance_tags(ai_output) == ["直播电商", "北京市"]

    def test_legacy_5dim_dict_recurses_via_add_many(self) -> None:
        ai_output = {
            "tags": {
                "professional_domain": [{"value": "直播电商"}],
                "geographic_scope": [{"value": "北京市"}],
            }
        }
        # Order follows dict iteration (Python 3.7+ insertion order)
        assert _extract_governance_tags(ai_output) == ["直播电商", "北京市"]


class TestStagesLayerHandling:
    def test_stages_tagging_structured_payload_flattens(self) -> None:
        ai_output = {
            "tags": [],
            "_stages": {
                "tagging": {
                    "tags": {
                        "regions": [{"value": "北京市"}],
                        "industries": [{"value": "直播电商"}],
                    }
                }
            },
        }
        assert _extract_governance_tags(ai_output) == ["北京市", "直播电商"]

    def test_stages_tagging_legacy_payload_still_works(self) -> None:
        ai_output = {
            "tags": [],
            "_stages": {
                "tagging": {
                    "tags": {
                        "professional_domain": [{"value": "直播电商"}],
                    }
                }
            },
        }
        assert _extract_governance_tags(ai_output) == ["直播电商"]
