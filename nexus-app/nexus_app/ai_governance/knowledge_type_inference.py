"""Knowledge type inference for AI governance.

Infers primary and co-emission knowledge types from normalized_asset_ref.
"""

from __future__ import annotations

import logging
from typing import Any

from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry

logger = logging.getLogger(__name__)


class KnowledgeTypeInferenceError(Exception):
    pass


def infer_knowledge_emissions(
    ai_output: dict[str, Any],
    ref_dict: dict[str, Any],
    registry: GovernanceRulesRegistry,
) -> list[dict[str, Any]]:
    """Infer knowledge_emissions from AI output.

    Returns:
        List of emissions with structure:
        [
            {
                "code": str,
                "name": str,
                "primary": bool,
                "confidence": float,
                "source": "ai_inference",
                "evidence": list[str],
                "co_emission_origin": str | None
            },
            ...
        ]

    The first emission with primary=True is the main knowledge type.
    Subsequent emissions are co_emissions triggered by co_emission_rules.
    """
    emissions: list[dict[str, Any]] = []

    # Step 1: Infer primary knowledge type
    primary_code, primary_confidence, primary_evidence = _infer_primary_knowledge_type(
        ai_output, ref_dict, registry
    )

    if not primary_code:
        logger.warning("No primary knowledge type inferred from AI output")
        return []

    primary_kt_config = registry.get_knowledge_type(primary_code)
    if not primary_kt_config:
        logger.warning(f"Knowledge type '{primary_code}' not found in registry")
        return []

    emissions.append({
        "code": primary_code,
        "name": primary_kt_config.get("name", primary_code),
        "primary": True,
        "confidence": primary_confidence,
        "source": "ai_inference",
        "evidence": primary_evidence,
        "co_emission_origin": None,
    })

    # Step 2: Evaluate co_emission_rules
    co_emission_rules = primary_kt_config.get("co_emission_rules", [])
    for rule in co_emission_rules:
        target_code = rule.get("target_code")
        condition = rule.get("condition")
        min_confidence = rule.get("min_confidence", 0.6)

        if not target_code or not condition:
            continue

        # Evaluate condition
        co_confidence = _evaluate_co_emission_condition(
            condition, ai_output, ref_dict
        )

        if co_confidence >= min_confidence:
            target_kt_config = registry.get_knowledge_type(target_code)
            if target_kt_config:
                emissions.append({
                    "code": target_code,
                    "name": target_kt_config.get("name", target_code),
                    "primary": False,
                    "confidence": co_confidence,
                    "source": "co_emission_rule",
                    "evidence": [f"Triggered by {primary_code} co_emission_rule: {condition}"],
                    "co_emission_origin": primary_code,
                })
                logger.info(
                    f"Co-emission triggered: {target_code} from {primary_code} "
                    f"(confidence={co_confidence:.2f}, condition={condition})"
                )
            else:
                logger.warning(f"Co-emission target '{target_code}' not found in registry")

    return emissions


def _infer_primary_knowledge_type(
    ai_output: dict[str, Any],
    ref_dict: dict[str, Any],
    registry: GovernanceRulesRegistry,
) -> tuple[str | None, float, list[str]]:
    """Infer primary knowledge type from AI output.

    Returns:
        (knowledge_type_code, confidence, evidence_list)
    """
    # Check if AI output contains explicit knowledge_type field
    if "knowledge_type" in ai_output:
        kt_output = ai_output["knowledge_type"]
        if isinstance(kt_output, dict):
            code = kt_output.get("code")
            confidence = kt_output.get("confidence", 0.8)
            evidence = kt_output.get("evidence", [])
            if code:
                return code, confidence, evidence

    # Fallback: infer from classification and content_type
    classification = ai_output.get("classification")
    content_type = ref_dict.get("content_type", "")
    source_type_hint = ref_dict.get("source_type_hint", "")

    # Simple heuristic mapping (should be enhanced with actual AI inference)
    if classification == "D4":
        if "教材" in content_type or "课件" in content_type:
            return "textbook_kb", 0.75, ["Classification D4 + content_type contains 教材/课件"]
        if "问答" in content_type or "QA" in content_type.upper():
            return "qa_corpus", 0.75, ["Classification D4 + content_type contains 问答/QA"]

    if classification == "D3":
        if "培养方案" in content_type or "课程体系" in content_type:
            return "talent_training_dataset", 0.75, ["Classification D3 + content_type contains 培养方案/课程体系"]

    if classification == "D2":
        if "流程" in content_type or "操作" in content_type:
            return "business_process_doc", 0.7, ["Classification D2 + content_type contains 流程/操作"]

    # Default: no primary type inferred
    logger.warning(
        f"Could not infer primary knowledge type from classification={classification}, "
        f"content_type={content_type}"
    )
    return None, 0.0, []


def _evaluate_co_emission_condition(
    condition: str,
    ai_output: dict[str, Any],
    ref_dict: dict[str, Any],
) -> float:
    """Evaluate co_emission condition and return confidence score.

    Conditions are simple string patterns for P0. P1 should use JSONLogic or similar.

    Returns:
        Confidence score (0.0 - 1.0)
    """
    # P0 heuristic evaluation
    if condition == "contains_qa_pairs":
        # Check if content suggests Q&A structure
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary for kw in ["问答", "q&a", "问题", "答案"]):
            return 0.7
        return 0.3

    if condition == "contains_concept_relations":
        # Check if content suggests concept relationships
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary for kw in ["概念", "关系", "知识图谱", "依赖"]):
            return 0.7
        return 0.3

    if condition == "contains_process_steps":
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary for kw in ["步骤", "流程", "操作", "指南"]):
            return 0.7
        return 0.3

    if condition == "contains_indicators":
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary for kw in ["指标", "kpi", "考核", "评估"]):
            return 0.7
        return 0.3

    if condition == "contains_case_studies":
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary for kw in ["案例", "实例", "场景"]):
            return 0.7
        return 0.3

    # Unknown condition
    logger.warning(f"Unknown co_emission condition: {condition}")
    return 0.0
