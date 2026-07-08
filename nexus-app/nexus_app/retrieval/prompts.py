"""Prompt construction for retrieval/recall orchestration."""
from __future__ import annotations

import json
from typing import Any

from nexus_app.retrieval.domain_registry import list_domain_definitions
from nexus_app.retrieval.schemas import INTENT_CONFIDENCE_THRESHOLD


def build_intent_recognition_messages(
    query: str,
    *,
    confidence_threshold: float = INTENT_CONFIDENCE_THRESHOLD,
) -> list[dict[str, str]]:
    """Build schema-constrained messages for retrieval intent recognition."""
    payload = {
        "user_query": query,
        "confidence_threshold": confidence_threshold,
        "domains": [_domain_to_prompt_payload(definition) for definition in list_domain_definitions()],
        "allowed_channels": ["unstructured", "structured", "hybrid"],
        "required_output_schema": {
            "business_domains": ["one or more registered domain codes"],
            "retrieval_channels": ["unstructured | structured | hybrid"],
            "question_type": "short controlled label such as definition, aggregation, comparison",
            "output_expectation": ["summary", "table", "sources"],
            "constraints": {"key": "value"},
            "confidence": "number between 0 and 1",
            "candidate_intents": [
                {
                    "business_domain": "registered domain code",
                    "question_type": "candidate type",
                    "confidence": "number between 0 and 1",
                }
            ],
            "missing_constraints": ["missing data needed to disambiguate"],
            "suggested_refinements": ["short user-facing refinement suggestion"],
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 NEXUS 企业数据与知识资产平台的检索意图识别器。"
                "只能基于给定领域字典判断用户问题应映射到哪些业务领域、检索通道和问题类型。"
                "必须只输出 JSON，不要输出 Markdown 或解释。"
                "当意图不清晰或置信度低于阈值时，仍输出候选意图、缺失约束和建议补充项。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]


def _domain_to_prompt_payload(definition: Any) -> dict[str, Any]:
    return {
        "domain": definition.domain,
        "display_name": definition.display_name,
        "default_channel": definition.default_channel,
        "allowed_channels": list(definition.allowed_channels),
        "query_profiles": [
            {
                "key": profile.key,
                "channel": profile.channel,
                "description": profile.description,
                "table_profile": profile.table_profile,
                "allowed_filters": list(profile.allowed_filters),
                "allowed_group_by": list(profile.allowed_group_by),
            }
            for profile in definition.query_profiles
        ],
    }

