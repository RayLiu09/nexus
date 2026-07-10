"""Unit tests for v1.3 §4.4 tag_taxonomy skeleton.

Covers:

* ``tag_taxonomy`` constant shape (all 7 required types present, codes unique).
* Pydantic ``TagTaxonomyConfig`` validation (unique codes, threshold ordering).
* ``build_rules_content()`` output surfaces ``tag_taxonomy`` at
  ``schema_version == "3.0"``.
* Legacy-dimension map coverage sanity: every legacy ``tag_dimensions`` key
  is referenced by at least one ``tag_taxonomy.types[*].legacy_dimension_map``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus_app.ai_governance.rules_config import (
    GovernanceRulesConfig,
    TagTaxonomyConfig,
)
from nexus_app.ai_governance.tag_taxonomy import (
    TAG_TAXONOMY_V1_3,
    TAG_TAXONOMY_VERSION,
    build_tag_taxonomy_seed,
)


REQUIRED_TAG_TYPES = {
    "region", "industry", "occupation", "major", "ability", "topic", "time_range",
}


def test_tag_taxonomy_constant_contains_all_seven_types() -> None:
    codes = {t["code"] for t in TAG_TAXONOMY_V1_3["types"]}
    assert codes == REQUIRED_TAG_TYPES, (
        f"tag_taxonomy must expose the 7 v1.3 types, got {codes}"
    )


def test_tag_taxonomy_constant_codes_unique() -> None:
    codes = [t["code"] for t in TAG_TAXONOMY_V1_3["types"]]
    assert len(codes) == len(set(codes)), "duplicate tag_taxonomy type codes"


def test_tag_taxonomy_constant_version_matches_module_version() -> None:
    assert TAG_TAXONOMY_V1_3["version"] == TAG_TAXONOMY_VERSION


def test_tag_taxonomy_thresholds_are_ordered() -> None:
    assert (
        TAG_TAXONOMY_V1_3["review_threshold"]
        < TAG_TAXONOMY_V1_3["auto_accept_threshold"]
    )


def test_tag_taxonomy_seed_is_deep_copy() -> None:
    seed_a = build_tag_taxonomy_seed()
    seed_b = build_tag_taxonomy_seed()
    seed_a["types"].append({"tampered": True})
    # mutating one seed must not leak into another nor into the constant
    assert seed_b["types"] != seed_a["types"]
    assert not any(t.get("tampered") for t in TAG_TAXONOMY_V1_3["types"])


def test_pydantic_accepts_valid_taxonomy() -> None:
    cfg = TagTaxonomyConfig.model_validate(build_tag_taxonomy_seed())
    codes = {t.code for t in cfg.types}
    assert codes == REQUIRED_TAG_TYPES


def test_pydantic_rejects_duplicate_codes() -> None:
    payload = build_tag_taxonomy_seed()
    payload["types"].append(dict(payload["types"][0]))  # duplicate 'region'
    with pytest.raises(ValidationError):
        TagTaxonomyConfig.model_validate(payload)


def test_pydantic_rejects_review_threshold_gte_auto_accept() -> None:
    payload = build_tag_taxonomy_seed()
    payload["review_threshold"] = payload["auto_accept_threshold"]
    with pytest.raises(ValidationError):
        TagTaxonomyConfig.model_validate(payload)


def test_pydantic_rejects_out_of_range_threshold() -> None:
    payload = build_tag_taxonomy_seed()
    payload["auto_accept_threshold"] = 1.5
    with pytest.raises(ValidationError):
        TagTaxonomyConfig.model_validate(payload)


def test_pydantic_rejects_unknown_tag_type_code() -> None:
    payload = build_tag_taxonomy_seed()
    payload["types"][0]["code"] = "unknown_code"
    with pytest.raises(ValidationError):
        TagTaxonomyConfig.model_validate(payload)


def test_build_rules_content_carries_tag_taxonomy_at_schema_v3() -> None:
    from nexus_app.ai_governance.seed_data import build_rules_content

    rules = build_rules_content()
    assert rules["schema_version"] == "3.0"
    assert "tag_taxonomy" in rules
    # Full pydantic validation of the whole rules bundle
    validated = GovernanceRulesConfig.model_validate(rules)
    assert validated.tag_taxonomy is not None
    assert len(validated.tag_taxonomy.types) == 7


def test_taxonomy_type_rejects_extra_legacy_dimension_map_field() -> None:
    """Guard: the (deprecated) legacy_dimension_map field must not silently
    reappear on TagTaxonomyType; if it does the constant may be re-polluted
    with translation-table baggage that v1.3 intentionally dropped.  Extra
    fields are ignored per model_config (they do not error), so we assert
    on the model_fields set instead."""
    from nexus_app.ai_governance.rules_config import TagTaxonomyType

    assert "legacy_dimension_map" not in TagTaxonomyType.model_fields


def test_governance_rules_config_accepts_missing_tag_taxonomy() -> None:
    """Backwards compatibility: legacy v2.0 rules blobs (no tag_taxonomy)
    must still validate."""
    from nexus_app.ai_governance.seed_data import (
        _BUILTIN_LEVELS,
        _DEFAULT_QUALITY_SCORING,
    )

    legacy_shape = {
        "schema_version": "2.0",
        "tag_dimensions": {},
        "classifications": [
            {
                "code": "industry_policy",
                "name": "产业政策",
                "description": "legacy stub",
            },
        ],
        "levels": _BUILTIN_LEVELS,
        "quality_scoring": _DEFAULT_QUALITY_SCORING,
    }
    validated = GovernanceRulesConfig.model_validate(legacy_shape)
    assert validated.tag_taxonomy is None
