"""Regression coverage for the document-and-outline tag-index boundary."""

from nexus_app.ai_governance.projection_config import (
    PROJECTION_WHITELIST_V1_3,
    get_field_projections,
)
from nexus_app.ai_governance.tag_projection import _TABLE_TO_TARGET_TYPE


def test_only_document_and_outline_projection_tables_are_registered() -> None:
    assert set(PROJECTION_WHITELIST_V1_3) == {
        "major_profile_ability",
        "knowledge_outline_node",
        "task_outline_node",
    }
    assert set(_TABLE_TO_TARGET_TYPE) == set(PROJECTION_WHITELIST_V1_3)


def test_outline_nodes_keep_topic_tag_projection() -> None:
    assert get_field_projections("knowledge_outline_node") == {"title": ["topic"]}
    assert get_field_projections("task_outline_node") == {"title": ["topic"]}


def test_pipeline_b_structured_tables_have_no_tag_projection_contract() -> None:
    retired = {
        "job_demand_record",
        "job_demand_requirement_item",
        "major_distribution_record",
        "occupational_ability_item",
    }
    assert retired.isdisjoint(PROJECTION_WHITELIST_V1_3)
    assert retired.isdisjoint(_TABLE_TO_TARGET_TYPE)
