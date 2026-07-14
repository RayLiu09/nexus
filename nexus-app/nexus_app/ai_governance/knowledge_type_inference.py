"""Knowledge type inference for AI governance — DETERMINISTIC, rule-driven.

Per docs/document_normalize_defects.md §12 (review-gated rules-v2):

  - The primary knowledge type is NOT inferred by the AI model. It is a
    deterministic lookup against the active governance rules:
    ``classification → classification.primary_knowledge_type``.
  - A classification produces at most one knowledge-processing emission.
    Graph construction is declared as metadata on that primary emission, not
    as a second knowledge type.
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
      3. Copy declared graph metadata from the primary knowledge type when
         present. This does not create another emission.

    Returns ``[]`` when:
      - the AI output carries no classification, or
      - the classification is not in the active rules, or
      - the rule sets ``primary_knowledge_type`` to None/missing, or
      - the targeted KT is not in the rule file.

    Output element schema:
      ``{code, name, primary, confidence, source, evidence,
         co_emission_origin, graph_profile?}``.
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

    emission: dict[str, Any] = {
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
    }
    graph_profile = primary_kt_config.get("graph_profile")
    if isinstance(graph_profile, str) and graph_profile.strip():
        emission["graph_profile"] = graph_profile.strip()
    return [emission]


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
        # Teaching standards normally express their relation-bearing structure
        # through occupational roles, objectives, specifications and curricula,
        # not the literal phrase "knowledge graph".
        content_snippet = ref_dict.get("content_snippet", "").lower()
        summary = ref_dict.get("summary", "").lower()
        if any(kw in content_snippet or kw in summary for kw in [
            "概念", "关系", "知识图谱", "依赖", "职业面向", "培养目标",
            "培养规格", "课程设置", "课程体系", "岗位", "能力要求",
        ]):
            return 0.75
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
