"""Knowledge type inference for AI governance — DETERMINISTIC, rule-driven.

Per docs/document_normalize_defects.md §12 (review-gated rules-v2):

  - The primary knowledge type is NOT inferred by the AI model. It is a
    deterministic lookup against the active governance rules:
    ``classification → classification.primary_knowledge_type``.
  - Co-emission rules also live on the **classification** (not the KT),
    again read from the active rules at decision time.
  - The D1-D4 fallback heuristics (which never matched the v3.0 business
    codes the AI actually emits) are deleted.

The AI run only contributes ``classification`` (and the cell-content signals
used by co-emission ``condition`` evaluation). Everything else is rules.
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
    """Return knowledge_emissions for the given AI run output.

    Determinism contract:
      1. Read ``ai_output['classification']`` (e.g. ``sector_report``).
      2. Look up the classification in the **active** governance rules; the
         classification's ``primary_knowledge_type`` is the canonical primary
         emission. No model inference, no string heuristics.
      3. Walk the classification's ``co_emission_rules`` and emit any whose
         ``condition`` evaluates ≥ ``min_confidence`` against ``ai_output`` /
         ``ref_dict``.

    Returns ``[]`` when:
      - the AI output carries no classification, or
      - the classification is not in the active rules, or
      - the rule sets ``primary_knowledge_type`` to None/missing, or
      - the targeted KT is not in the rule file.

    Output element schema:
      ``{code, name, primary, confidence, source, evidence,
         co_emission_origin}``
      where ``source ∈ {"rule_lookup", "co_emission_rule"}``.
    """
    classification = ai_output.get("classification") if isinstance(ai_output, dict) else None
    if not classification or not isinstance(classification, str):
        logger.warning(
            "infer_knowledge_emissions: AI output lacks classification — no emissions"
        )
        return []

    cls_def = next(
        (c for c in registry.get_classifications() if c.code == classification),
        None,
    )
    if cls_def is None:
        logger.warning(
            "infer_knowledge_emissions: classification %r not present in active rules "
            "(active rules schema may need updating)", classification,
        )
        return []

    primary_code = cls_def.primary_knowledge_type
    if not primary_code:
        logger.warning(
            "infer_knowledge_emissions: classification %r has no primary_knowledge_type "
            "configured in active rules — no emissions", classification,
        )
        return []

    primary_kt_config = registry.get_knowledge_type(primary_code)
    if not primary_kt_config:
        logger.warning(
            "infer_knowledge_emissions: primary_knowledge_type %r referenced by "
            "classification %r is not defined in active rules' knowledge_types section",
            primary_code, classification,
        )
        return []

    # Primary emission confidence inherits the AI classification confidence
    # (a rule lookup is deterministic, but downstream telemetry still wants to
    # know how sure the AI was about the classification it produced).
    primary_confidence = float(ai_output.get("confidence", 1.0))

    emissions: list[dict[str, Any]] = [{
        "code": primary_code,
        "name": primary_kt_config.get("name", primary_code),
        "primary": True,
        "confidence": primary_confidence,
        "source": "rule_lookup",
        "evidence": [
            f"classification={classification} → primary_knowledge_type={primary_code} "
            f"(active rules)"
        ],
        "co_emission_origin": None,
    }]

    # Co-emission rules live on the CLASSIFICATION (rule-driven), not on the
    # KT (which kept its own list in the old file but is no longer the source
    # of truth under v2.1).
    for rule in cls_def.co_emission_rules:
        target_code = rule.target_code
        condition = rule.condition
        min_confidence = rule.min_confidence

        if not target_code or not condition:
            continue

        target_kt_config = registry.get_knowledge_type(target_code)
        if not target_kt_config:
            logger.warning(
                "co-emission target %r (from classification %r) not in registry",
                target_code, classification,
            )
            continue

        co_confidence = _evaluate_co_emission_condition(condition, ai_output, ref_dict)
        if co_confidence < min_confidence:
            continue

        emissions.append({
            "code": target_code,
            "name": target_kt_config.get("name", target_code),
            "primary": False,
            "confidence": co_confidence,
            "source": "co_emission_rule",
            "evidence": [
                f"triggered by classification.{classification} co_emission_rule: "
                f"{condition} (confidence {co_confidence:.2f} >= {min_confidence:.2f})"
            ],
            "co_emission_origin": primary_code,
        })
        logger.info(
            "co-emission: %s (from classification=%s, condition=%s, conf=%.2f)",
            target_code, classification, condition, co_confidence,
        )

    return emissions


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

    if condition == "contains_skill_taxonomy":
        # competency_analysis → skill_tag_library (v2 rules §12).
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary
               for kw in ["技能点", "技能要求", "能力点", "技能等级", "技能标签"]):
            return 0.75
        return 0.3

    if condition == "contains_competency_breakdown":
        # talent_training_plan → competency_graph (v2 rules §12).
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary
               for kw in ["能力分解", "能力图谱", "岗位能力", "职业能力", "胜任力"]):
            return 0.75
        return 0.3

    # Unknown condition
    logger.warning(f"Unknown co_emission condition: {condition}")
    return 0.0
