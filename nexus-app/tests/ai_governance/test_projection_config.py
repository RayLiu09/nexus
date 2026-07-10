"""Static guards for the cross-asset projection whitelist v0.1
(v1.3 revision round 2, §2.4).

These tests intentionally freeze the projection contract so that:

* silent drift of the ``item_type='professional_skill'`` rule surfaces here,
* projections do not point at ``tag_taxonomy`` codes that no longer exist,
* the field lists remain aligned with the actual SQLAlchemy models
  (renaming a column upstream must break these tests first, before it
  breaks the projection hook in production).
"""

from __future__ import annotations

import pytest

from nexus_app.ai_governance.projection_config import (
    PROJECTION_WHITELIST_V1_3,
    PROJECTION_WHITELIST_VERSION,
    get_conditional_projections,
    get_field_projections,
    get_local_only_filters,
    get_long_text_fields,
    iter_tables,
)
from nexus_app.ai_governance.tag_taxonomy import TAG_TAXONOMY_V1_3


def _valid_tag_type_codes() -> set[str]:
    return {t["code"] for t in TAG_TAXONOMY_V1_3["types"]}


class TestGeneralInvariants:
    def test_version_matches_module_constant(self) -> None:
        assert PROJECTION_WHITELIST_VERSION == "0.1"

    def test_iter_tables_matches_whitelist_keys(self) -> None:
        assert set(iter_tables()) == set(PROJECTION_WHITELIST_V1_3.keys())

    def test_missing_table_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="no projection whitelist entry"):
            get_field_projections("does_not_exist")

    def test_all_projection_targets_are_registered_tag_types(self) -> None:
        """A projection target that isn't in tag_taxonomy would silently
        produce orphan tag_asset_index rows.  Fail fast at test-time."""
        valid_codes = _valid_tag_type_codes()
        for table in PROJECTION_WHITELIST_V1_3:
            for field, targets in get_field_projections(table).items():
                for t in targets:
                    assert t in valid_codes, (
                        f"{table}.{field} projects to unknown tag_type {t!r}"
                    )
            for rule in get_conditional_projections(table):
                for t in rule.get("target_tag_types", []):
                    assert t in valid_codes, (
                        f"{table} conditional rule projects to unknown "
                        f"tag_type {t!r}"
                    )
            # metadata_projections is optional; validate when present
            meta = PROJECTION_WHITELIST_V1_3[table].get("metadata_projections", {})
            for path, targets in meta.items():
                for t in targets:
                    assert t in valid_codes, (
                        f"{table}.{path} projects to unknown tag_type {t!r}"
                    )


class TestJobDemand:
    def test_record_projections_are_the_four_cross_asset_dimensions(self) -> None:
        proj = get_field_projections("job_demand_record")
        assert proj == {
            "city": ["region"],
            "industry_name": ["industry"],
            "job_title": ["occupation"],
            "source_published_at": ["time_range"],
        }

    def test_local_only_covers_salary_and_experience(self) -> None:
        local = set(get_local_only_filters("job_demand_record"))
        for expected in (
            "employment_type",
            "experience_requirement",
            "education_requirement",
            "salary_min",
            "salary_max",
            "enterprise_size",
        ):
            assert expected in local, f"expected {expected!r} in local_only_filters"

    def test_free_text_fields_are_neither_projected_nor_filtered(self) -> None:
        long_text = set(get_long_text_fields("job_demand_record"))
        for expected in (
            "job_skill_text",
            "job_description",
            "responsibility_text",
            "requirement_text",
        ):
            assert expected in long_text
        # And they must not double-appear elsewhere.
        proj_fields = set(get_field_projections("job_demand_record").keys())
        local = set(get_local_only_filters("job_demand_record"))
        assert not (long_text & proj_fields)
        assert not (long_text & local)

    def test_requirement_item_only_professional_skill_is_projected(self) -> None:
        rules = get_conditional_projections("job_demand_requirement_item")
        assert len(rules) == 1
        rule = rules[0]
        assert rule["when"] == {"item_type": "professional_skill"}
        assert rule["value_field"] == ["normalized_name", "item_name"]
        assert rule["target_tag_types"] == ["ability", "topic"]

    def test_requirement_item_skips_all_other_item_types(self) -> None:
        skip = set(
            PROJECTION_WHITELIST_V1_3["job_demand_requirement_item"]["skip_item_types"]
        )
        expected_non_projected = {
            "tool",
            "certificate",
            "professional_literacy",
            "work_task_candidate",
        }
        assert skip == expected_non_projected


class TestMajorDistribution:
    def test_dimensions_cover_region_major_time(self) -> None:
        proj = get_field_projections("major_distribution_record")
        assert proj == {
            "province_name": ["region"],
            "major_name": ["major"],
            "major_code": ["major"],
            "year": ["time_range"],
        }

    def test_region_scope_stays_local_not_projected(self) -> None:
        """v1.3 R3: region_scope stores operational bucket values (e.g. "国家"
        / "省" / "市"), not real regions.  It must never be projected as a
        cross-asset region tag."""
        proj = get_field_projections("major_distribution_record")
        assert "region_scope" not in proj
        local = get_local_only_filters("major_distribution_record")
        assert "region_scope" in local

    def test_education_level_stays_local(self) -> None:
        assert "education_level" in get_local_only_filters(
            "major_distribution_record"
        )
        assert "education_level" not in get_field_projections(
            "major_distribution_record"
        )


class TestAbilityTables:
    def test_occupational_uses_ability_content_not_name(self) -> None:
        """v1.3 revision: the cross-asset semantic anchor is
        ability_content (human-readable statement), not the internal
        ability_code / ability_sequence which carry no shared vocabulary."""
        proj = get_field_projections("occupational_ability_item")
        assert proj == {"ability_content": ["ability"]}

    def test_occupational_local_only_covers_all_internal_codes(self) -> None:
        local = set(get_local_only_filters("occupational_ability_item"))
        for expected in (
            "ability_code",
            "ability_major_category_code",
            "ability_major_category_name",
            "ability_sequence",
        ):
            assert expected in local, (
                f"internal code {expected!r} must stay local, never projected"
            )

    def test_major_profile_ability_projects_text(self) -> None:
        proj = get_field_projections("major_profile_ability")
        assert proj == {"text": ["ability"]}


class TestOutlineNodes:
    def test_knowledge_outline_title_and_keywords_project_to_topic(self) -> None:
        proj = get_field_projections("knowledge_outline_node")
        assert proj == {"title": ["topic"]}
        meta = PROJECTION_WHITELIST_V1_3["knowledge_outline_node"][
            "metadata_projections"
        ]
        assert meta == {"node_metadata.keywords": ["topic"]}

    def test_task_outline_title_projects_to_topic(self) -> None:
        proj = get_field_projections("task_outline_node")
        assert proj == {"title": ["topic"]}


class TestScopeVsExampleInPrompt:
    """The v1.3 revision requires the tagging prompt to enforce main-scope
    vs example-scope distinction.  Guard against the instructions being
    edited away."""

    def test_prompt_mentions_scope_vs_example_rule(self) -> None:
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        body = V1_3_PROMPT_UPGRADES["tagging"]["prompt_template"]
        # main / example rule keywords
        for kw in ("主体范围", "举例范围"):
            assert kw in body, f"prompt missing scope-vs-example keyword: {kw}"
        # the four affected categories must be named
        for cat in ("regions", "industries", "occupations", "majors"):
            assert cat in body, f"prompt missing category name: {cat}"
        # cautionary heuristics
        for hint in ("以…为例", "参考", "适用范围", "本规划", "宁少勿滥"):
            assert hint in body, f"prompt missing scope hint: {hint}"

    def test_prompt_change_summary_mentions_scope_rule(self) -> None:
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        summary = V1_3_PROMPT_UPGRADES["tagging"]["change_summary"]
        assert "主体" in summary
        assert "举例" in summary
