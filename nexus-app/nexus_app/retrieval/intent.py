"""LiteLLM-backed intent recognition for retrieval/recall orchestration."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
    LiteLLMConfig,
    create_litellm_client,
)
from nexus_app.config import Settings, get_settings
from nexus_app.retrieval.prompts import build_intent_recognition_messages
from nexus_app.retrieval.schemas import (
    ACCESS_SCOPE_ALL_ASSETS,
    Clarification,
    ContextPackStatus,
    ConversationStep,
    ConversationStepName,
    RetrievalContextPack,
    RetrievalIntent,
    StepStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentRecognitionResult:
    status: ContextPackStatus
    intent: RetrievalIntent | None
    conversation_step: ConversationStep
    context_pack: RetrievalContextPack | None = None
    model_alias: str | None = None
    warnings: tuple[str, ...] = ()


class IntentRecognitionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_client: LiteLLMClientProtocol | None = None,
        model_alias: str | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm_client = llm_client or _create_default_intent_llm_client(self._settings)
        self._model_alias = model_alias or self._settings.effective_retrieval_intent_model_alias
        self._confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else self._settings.retrieval_intent_confidence_threshold
        )

    def recognize(self, query: str) -> IntentRecognitionResult:
        messages = build_intent_recognition_messages(
            query,
            confidence_threshold=self._confidence_threshold,
        )
        try:
            content, summary = self._llm_client.call(
                self._model_alias,
                messages,
                temperature=0.0,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError as exc:
            logger.warning("retrieval intent LiteLLM call failed error_type=%s", exc.error_type)
            return self._failed_result(query, "intent_llm_call_failed")

        try:
            intent = self._parse_intent(content)
        except ValueError:
            logger.warning(
                "retrieval intent output invalid model_alias=%s request_id=%s",
                self._model_alias,
                summary.request_id,
            )
            return self._failed_result(query, "intent_schema_invalid")

        if intent.confidence < self._confidence_threshold:
            return self._clarification_result(query, intent)

        step = _intent_step(
            status=StepStatus.COMPLETED,
            intent=intent,
            message="意图识别完成",
        )
        return IntentRecognitionResult(
            status=ContextPackStatus.COMPLETED,
            intent=intent,
            conversation_step=step,
            model_alias=self._model_alias,
        )

    def _parse_intent(self, content: str) -> RetrievalIntent:
        try:
            payload = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ValueError("intent output is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("intent output must be a JSON object")
        payload.setdefault("confidence_threshold", self._confidence_threshold)
        try:
            return RetrievalIntent.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("intent output does not match RetrievalIntent schema") from exc

    def _clarification_result(self, query: str, intent: RetrievalIntent) -> IntentRecognitionResult:
        clarification = _clarification_from_intent(intent)
        step = _intent_step(
            status=StepStatus.NEEDS_CLARIFICATION,
            intent=intent,
            message=clarification.message,
        )
        pack = RetrievalContextPack(
            status=ContextPackStatus.NEEDS_CLARIFICATION,
            original_query=query,
            intent=intent,
            conversation_steps=[
                step,
                ConversationStep(
                    step=ConversationStepName.QUERY_TRANSFORMATION,
                    status=StepStatus.BLOCKED,
                    title="召回计划",
                    message="意图置信度低于阈值，等待用户优化问题或确认继续。",
                ),
            ],
            clarification=clarification,
            access_scope=ACCESS_SCOPE_ALL_ASSETS,
            warnings=["intent_confidence_below_threshold"],
        )
        return IntentRecognitionResult(
            status=ContextPackStatus.NEEDS_CLARIFICATION,
            intent=intent,
            conversation_step=step,
            context_pack=pack,
            model_alias=self._model_alias,
            warnings=("intent_confidence_below_threshold",),
        )

    def _failed_result(self, query: str, reason: str) -> IntentRecognitionResult:
        intent = RetrievalIntent(
            business_domains=["course_textbook"],
            retrieval_channels=["unstructured"],
            question_type="unknown",
            confidence=0.0,
            confidence_threshold=self._confidence_threshold,
            missing_constraints=["数据领域", "问题目标"],
            suggested_refinements=[
                "请补充要查询的数据领域，例如岗位需求、职业能力、专业布点或教材内容。",
                "请说明希望得到统计表、知识解释、操作步骤还是来源定位。",
            ],
        )
        clarification = _clarification_from_intent(intent)
        step = _intent_step(
            status=StepStatus.FAILED,
            intent=intent,
            message="意图识别结果无法通过 schema 校验。",
        )
        pack = RetrievalContextPack(
            status=ContextPackStatus.NEEDS_CLARIFICATION,
            original_query=query,
            intent=intent,
            conversation_steps=[step],
            clarification=clarification,
            access_scope=ACCESS_SCOPE_ALL_ASSETS,
            warnings=[reason],
        )
        return IntentRecognitionResult(
            status=ContextPackStatus.NEEDS_CLARIFICATION,
            intent=intent,
            conversation_step=step,
            context_pack=pack,
            model_alias=self._model_alias,
            warnings=(reason,),
        )


def create_intent_recognition_service(
    settings: Settings | None = None,
    *,
    llm_client: LiteLLMClientProtocol | None = None,
    model_alias: str | None = None,
    confidence_threshold: float | None = None,
) -> IntentRecognitionService:
    return IntentRecognitionService(
        settings=settings,
        llm_client=llm_client,
        model_alias=model_alias,
        confidence_threshold=confidence_threshold,
    )


def _create_default_intent_llm_client(settings: Settings) -> LiteLLMClientProtocol:
    if not settings.litellm_endpoint:
        raise RuntimeError("LITELLM_ENDPOINT is required for retrieval intent recognition")
    if not settings.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is required for retrieval intent recognition")
    return create_litellm_client(
        LiteLLMConfig(
            base_url=settings.litellm_endpoint.rstrip("/"),
            api_key_ref="LITELLM_API_KEY",
            timeout=settings.litellm_timeout,
        ),
        settings.litellm_api_key,
    )


def _intent_step(
    *,
    status: StepStatus,
    intent: RetrievalIntent,
    message: str,
) -> ConversationStep:
    return ConversationStep(
        step=ConversationStepName.INTENT_RECOGNITION,
        status=status,
        title="意图识别",
        message=message,
        display_payload={
            "business_domains": intent.business_domains,
            "retrieval_channels": intent.retrieval_channels,
            "question_type": intent.question_type,
            "constraints": intent.constraints,
            "confidence": intent.confidence,
            "confidence_threshold": intent.confidence_threshold,
            "candidate_intents": [
                candidate.model_dump() for candidate in intent.candidate_intents
            ],
            "missing_constraints": intent.missing_constraints,
            "suggested_refinements": intent.suggested_refinements,
        },
    )


def _clarification_from_intent(intent: RetrievalIntent) -> Clarification:
    suggestions = intent.suggested_refinements or [
        "请补充要查询的数据领域，例如岗位需求、职业能力、专业布点或教材内容。",
        "请补充时间、地区、专业名称、岗位名称等约束条件。",
        "请说明希望得到统计表、知识解释、操作步骤还是来源定位。",
    ]
    return Clarification(
        message="当前问题的检索意图不够清晰，是否愿意进一步优化问题？",
        suggested_refinements=suggestions,
        candidate_intents=intent.candidate_intents,
        missing_constraints=intent.missing_constraints,
    )

