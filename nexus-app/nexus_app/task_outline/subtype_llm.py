"""Optional LiteLLM arbitration for course-textbook subtype detection."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
    LiteLLMConfig,
    create_litellm_client,
)
from nexus_app.config import Settings, get_settings
from nexus_app.task_outline.detector import TextbookSubtypeDetection
from nexus_app.task_outline.normalizer import text_of
from nexus_app.task_outline.schemas import TEXTBOOK_SUBTYPES

logger = logging.getLogger(__name__)


class TextbookSubtypeArbiterProtocol(Protocol):
    def arbitrate(
        self,
        *,
        blocks: list[dict[str, Any]],
        body_markdown: str | None,
        rule_detection: TextbookSubtypeDetection,
    ) -> TextbookSubtypeDetection: ...


class TextbookSubtypeLlmDecision(BaseModel):
    textbook_subtype: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    reasoning: str | None = None

    @field_validator("textbook_subtype")
    @classmethod
    def _validate_subtype(cls, value: str) -> str:
        if value not in TEXTBOOK_SUBTYPES:
            raise ValueError(f"unsupported textbook_subtype {value!r}")
        return value


class LiteLLMTextbookSubtypeArbiter:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_client: LiteLLMClientProtocol | None = None,
        model_alias: str | None = None,
        block_limit: int | None = None,
        min_confidence: float | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm_client = llm_client or _create_default_llm_client(self._settings)
        self._model_alias = model_alias or self._settings.effective_task_outline_subtype_model_alias
        self._block_limit = block_limit or self._settings.task_outline_subtype_llm_block_limit
        self._min_confidence = (
            min_confidence
            if min_confidence is not None
            else self._settings.task_outline_subtype_llm_min_confidence
        )

    def arbitrate(
        self,
        *,
        blocks: list[dict[str, Any]],
        body_markdown: str | None,
        rule_detection: TextbookSubtypeDetection,
    ) -> TextbookSubtypeDetection:
        if not _needs_llm_arbitration(rule_detection):
            return rule_detection
        messages = build_subtype_arbitration_messages(
            blocks,
            body_markdown=body_markdown,
            rule_detection=rule_detection,
            block_limit=self._block_limit,
        )
        try:
            content, summary = self._llm_client.call(
                self._model_alias,
                messages,
                temperature=0.0,
                max_tokens=900,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError as exc:
            logger.warning("textbook subtype LiteLLM arbitration failed error_type=%s", exc.error_type)
            return _with_llm_warning(rule_detection, "llm_call_failed")

        try:
            decision = _parse_decision(content)
        except ValueError:
            logger.warning(
                "textbook subtype LLM arbitration schema invalid model_alias=%s request_id=%s",
                self._model_alias,
                summary.request_id,
            )
            return _with_llm_warning(rule_detection, "llm_schema_invalid")

        if decision.confidence < self._min_confidence:
            return _with_llm_warning(rule_detection, "llm_confidence_below_threshold")

        processing_profile, admission = _routing_for(decision.textbook_subtype)
        evidence = [
            f"LLM仲裁: {item}" for item in decision.evidence[:4] if item.strip()
        ] or ["LLM仲裁: 基于前置正文块判断教材内容本质"]
        if decision.reasoning:
            evidence.append(f"LLM仲裁理由: {decision.reasoning[:120]}")
        return replace(
            rule_detection,
            textbook_subtype=decision.textbook_subtype,
            subtype_confidence=round(decision.confidence, 4),
            processing_profile=processing_profile,
            evidence_graph_admission=admission,
            subtype_evidence=evidence,
            scores={
                **rule_detection.scores,
                "llm_confidence": round(decision.confidence, 4),
                "llm_override": 1.0,
            },
        )


def create_textbook_subtype_arbiter(
    settings: Settings | None = None,
    *,
    llm_client: LiteLLMClientProtocol | None = None,
    model_alias: str | None = None,
) -> TextbookSubtypeArbiterProtocol | None:
    settings = settings or get_settings()
    if not settings.task_outline_subtype_llm_enabled:
        return None
    return LiteLLMTextbookSubtypeArbiter(
        settings=settings,
        llm_client=llm_client,
        model_alias=model_alias,
    )


def build_subtype_arbitration_messages(
    blocks: list[dict[str, Any]],
    *,
    body_markdown: str | None,
    rule_detection: TextbookSubtypeDetection,
    block_limit: int,
) -> list[dict[str, str]]:
    excerpts = _block_excerpts(blocks, body_markdown=body_markdown, block_limit=block_limit)
    payload = {
        "task": "判断职业教育教材的内容本质子类型",
        "allowed_textbook_subtypes": sorted(TEXTBOOK_SUBTYPES),
        "decision_rules": [
            "theory_knowledge: 以概念、定义、原理、分类、机制、知识体系讲授为主；即使采用项目/任务包装，只要主体是知识讲解，也应归为此类。",
            "training_operation: 以完成真实工作任务、操作步骤、任务产物、表单填报、实训交付为主。",
            "hybrid: 理论讲授和操作实训都占明显主体，无法归入单一类型。",
            "unknown: 证据不足。",
        ],
        "rule_detection": {
            "textbook_subtype": rule_detection.textbook_subtype,
            "confidence": rule_detection.subtype_confidence,
            "scores": rule_detection.scores,
            "evidence": rule_detection.subtype_evidence,
        },
        "blocks": excerpts,
        "output_schema": {
            "textbook_subtype": "theory_knowledge|training_operation|hybrid|unknown",
            "confidence": "0..1",
            "evidence": ["short evidence without raw long text"],
            "reasoning": "short rationale",
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You classify Chinese vocational textbooks by content essence. "
                "Return only valid JSON. Prefer theory_knowledge when project/task "
                "labels wrap conceptual explanation rather than executable work training."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _needs_llm_arbitration(rule_detection: TextbookSubtypeDetection) -> bool:
    confidence = rule_detection.subtype_confidence
    task_score = rule_detection.scores.get("task_score", 0.0)
    theory_score = rule_detection.scores.get("theory_score", 0.0)
    if confidence < 0.82:
        return True
    if rule_detection.textbook_subtype in {"training_operation", "hybrid"}:
        return theory_score >= 6 and theory_score >= task_score * 0.45
    return False


def _block_excerpts(
    blocks: list[dict[str, Any]],
    *,
    body_markdown: str | None,
    block_limit: int,
) -> list[dict[str, Any]]:
    excerpts: list[dict[str, Any]] = []
    for index, block in enumerate(blocks[: max(1, block_limit)]):
        text = text_of(block)
        if not text:
            continue
        excerpts.append(
            {
                "index": index,
                "block_id": block.get("block_id"),
                "block_type": block.get("block_type") or block.get("type"),
                "heading_level": block.get("heading_level"),
                "text": text[:500],
            }
        )
    if not excerpts and body_markdown:
        excerpts.append({"index": 0, "block_type": "body_markdown", "text": body_markdown[:2000]})
    return excerpts


def _parse_decision(content: str) -> TextbookSubtypeLlmDecision:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("LLM subtype arbitration output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM subtype arbitration output must be a JSON object")
    try:
        return TextbookSubtypeLlmDecision.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("LLM subtype arbitration output schema invalid") from exc


def _with_llm_warning(
    detection: TextbookSubtypeDetection,
    warning: str,
) -> TextbookSubtypeDetection:
    return replace(
        detection,
        scores={**detection.scores, f"{warning}": 1.0},
    )


def _routing_for(subtype: str) -> tuple[str, str]:
    if subtype == "training_operation":
        return "task_outline", "not_recommended"
    if subtype == "theory_knowledge":
        return "evidence_graph", "recommended"
    if subtype == "hybrid":
        return "hybrid", "chapter_selective"
    return "semantic_only", "unknown"


def _create_default_llm_client(settings: Settings) -> LiteLLMClientProtocol:
    if not settings.litellm_endpoint:
        raise RuntimeError("LITELLM_ENDPOINT is required for textbook subtype arbitration")
    if not settings.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is required for textbook subtype arbitration")
    return create_litellm_client(
        LiteLLMConfig(
            base_url=settings.litellm_endpoint.rstrip("/"),
            api_key_ref="LITELLM_API_KEY",
            timeout=settings.litellm_timeout,
        ),
        settings.litellm_api_key,
    )
