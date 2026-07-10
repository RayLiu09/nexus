"""Tag taxonomy — cross-asset semantic-tag type skeleton (v1.3 retrieval side).

`tag_taxonomy` declares the *type skeleton* of business tags used for
cross-asset retrieval (see docs/knowledge_retrieval_result_enhancement_v1.3.md
§4.4).  It is complementary to the governance-side ``tag_dimensions`` block:

* ``tag_dimensions`` (governance side, rule-driven) tells the LLM *what values*
  to consider per classification (professional_domain, geographic_scope, …).
* ``tag_taxonomy`` (retrieval side, type-driven) tells the whole system *what
  tag types exist* across assets (region, industry, occupation, major,
  ability, topic, time_range) so that ``tag_asset_index`` inverted lookups,
  intent recognition, and retrieval planners share a single vocabulary.

Legacy ``governance_result.tags`` (flat string list) is *not* migrated by a
translation table.  Old assets are re-tagged via
``nexus_app.governance.recompute.recompute_tagging_only``, which reruns
only the ``tagging`` task_type against the upgraded prompt profile; other
task_types (classification / level / quality / knowledge_type_inference)
are untouched, so knowledge chunk emission and index manifests are not
cascaded.

``standard_code`` on a tag row is auto-filled *only* if a canonical
dictionary alias hit is found; misses do not block indexing or retrieval.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "TAG_TAXONOMY_VERSION",
    "TAG_TAXONOMY_V1_3",
    "build_tag_taxonomy_seed",
]

TAG_TAXONOMY_VERSION: str = "1.0"

# NOTE:  keep this constant in sync with docs/knowledge_retrieval_result_enhancement_v1.3.md §4.4.
#        Any change here must go through governance_rules schema_version bump.
TAG_TAXONOMY_V1_3: dict[str, Any] = {
    "version": TAG_TAXONOMY_VERSION,
    "types": [
        {
            "code": "region",
            "name": "地区",
            "description": "跨资产地理约束（省 / 市 / 区）",
            "canonical_source": "dim_region",
            "allow_free_form": True,
            "expected_cardinality": "low",
        },
        {
            "code": "industry",
            "name": "行业",
            "description": "国民经济行业 / 产业 / 业态",
            "canonical_source": "dim_industry",
            "allow_free_form": True,
            "expected_cardinality": "medium",
        },
        {
            "code": "occupation",
            "name": "职业",
            "description": "职业 / 岗位 / 工种",
            "canonical_source": "dim_occupation",
            "allow_free_form": True,
            "expected_cardinality": "medium",
        },
        {
            "code": "major",
            "name": "专业",
            "description": "教育部专业目录中的专业名称",
            "canonical_source": "dim_major",
            "allow_free_form": True,
            "expected_cardinality": "medium",
        },
        {
            "code": "ability",
            "name": "能力",
            "description": "职业能力项 / 技能 / 素养",
            "canonical_source": "dim_ability",
            "allow_free_form": True,
            "expected_cardinality": "high",
        },
        {
            "code": "topic",
            "name": "主题",
            "description": "核心主题 / 关键词 / 概念",
            "canonical_source": None,
            "allow_free_form": True,
            "expected_cardinality": "high",
        },
        {
            "code": "time_range",
            "name": "时间",
            "description": "时间范围 / 时效性",
            "canonical_source": "dim_time_bucket",
            "allow_free_form": True,
            "expected_cardinality": "low",
        },
    ],
    "auto_accept_threshold": 0.75,
    "review_threshold": 0.55,
    "notes": (
        "v1.3 跨资产语义标签骨架。与治理侧 tag_dimensions 互补："
        "tag_dimensions 是规则驱动（每类资产应打什么值），"
        "tag_taxonomy 是检索驱动（跨资产标签有哪些类型）。"
        "standard_code 命中字典时自动填充，未命中不阻塞检索。"
        "老 governance_result.tags 不做翻译式迁移，通过 recompute_tagging_only "
        "重跑仅 tagging task_type 完成升级。"
    ),
}


def build_tag_taxonomy_seed() -> dict[str, Any]:
    """Return the seed ``tag_taxonomy`` block for ``GovernanceRulesVersion``.

    Kept as a factory to allow future extension (e.g. per-classification
    overrides) without changing call sites.
    """
    # deep-copy semantics: consumers may mutate; keep the constant immutable
    import copy

    return copy.deepcopy(TAG_TAXONOMY_V1_3)
