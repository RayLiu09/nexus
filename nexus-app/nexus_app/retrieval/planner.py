"""LiteLLM-backed retrieval plan generation."""
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
from nexus_app.retrieval.prompts import build_retrieval_plan_messages
from nexus_app.retrieval.schemas import (
    ConversationStep,
    ConversationStepName,
    MAX_SUB_QUERIES,
    RetrievalIntent,
    RetrievalPlan,
    StepStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalPlannerResult:
    plan: RetrievalPlan | None
    conversation_step: ConversationStep
    model_alias: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def success(self) -> bool:
        return self.plan is not None and self.conversation_step.status == StepStatus.COMPLETED


class RetrievalPlannerService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm_client: LiteLLMClientProtocol | None = None,
        model_alias: str | None = None,
        max_sub_queries: int | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm_client = llm_client or _create_default_planner_llm_client(self._settings)
        self._model_alias = model_alias or self._settings.effective_retrieval_planner_model_alias
        configured_max = max_sub_queries or self._settings.retrieval_max_sub_queries
        self._max_sub_queries = max(1, min(configured_max, MAX_SUB_QUERIES))

    def generate_plan(self, query: str, intent: RetrievalIntent) -> RetrievalPlannerResult:
        messages = build_retrieval_plan_messages(
            query,
            intent,
            max_sub_queries=self._max_sub_queries,
        )
        try:
            content, summary = self._llm_client.call(
                self._model_alias,
                messages,
                temperature=0.0,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError as exc:
            logger.warning("retrieval planner LiteLLM call failed error_type=%s", exc.error_type)
            return self._failed_result("retrieval_plan_llm_call_failed")

        try:
            plan = self._parse_plan(content, fallback_query=query)
        except ValueError:
            logger.warning(
                "retrieval planner output invalid model_alias=%s request_id=%s",
                self._model_alias,
                summary.request_id,
            )
            return self._failed_result("retrieval_plan_schema_invalid")

        step = _plan_step(
            status=StepStatus.COMPLETED,
            message="召回计划生成完成",
            plan=plan,
        )
        return RetrievalPlannerResult(
            plan=plan,
            conversation_step=step,
            model_alias=self._model_alias,
        )

    def _parse_plan(self, content: str, *, fallback_query: str) -> RetrievalPlan:
        try:
            payload = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ValueError("retrieval plan output is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("retrieval plan output must be a JSON object")
        payload.setdefault("original_query", fallback_query)
        try:
            return RetrievalPlan.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("retrieval plan output does not match RetrievalPlan schema") from exc

    def _failed_result(self, reason: str) -> RetrievalPlannerResult:
        return RetrievalPlannerResult(
            plan=None,
            conversation_step=ConversationStep(
                step=ConversationStepName.QUERY_TRANSFORMATION,
                status=StepStatus.FAILED,
                title="召回计划",
                message="召回计划无法通过 schema 校验，未执行检索。",
                display_payload={"reason": reason},
            ),
            model_alias=self._model_alias,
            warnings=(reason,),
        )


def create_retrieval_planner_service(
    settings: Settings | None = None,
    *,
    llm_client: LiteLLMClientProtocol | None = None,
    model_alias: str | None = None,
    max_sub_queries: int | None = None,
) -> RetrievalPlannerService:
    return RetrievalPlannerService(
        settings=settings,
        llm_client=llm_client,
        model_alias=model_alias,
        max_sub_queries=max_sub_queries,
    )


def _create_default_planner_llm_client(settings: Settings) -> LiteLLMClientProtocol:
    if not settings.litellm_endpoint:
        raise RuntimeError("LITELLM_ENDPOINT is required for retrieval plan generation")
    if not settings.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is required for retrieval plan generation")
    return create_litellm_client(
        LiteLLMConfig(
            base_url=settings.litellm_endpoint.rstrip("/"),
            api_key_ref="LITELLM_API_KEY",
            timeout=settings.litellm_timeout,
        ),
        settings.litellm_api_key,
    )


def _plan_step(
    *,
    status: StepStatus,
    message: str,
    plan: RetrievalPlan,
) -> ConversationStep:
    return ConversationStep(
        step=ConversationStepName.QUERY_TRANSFORMATION,
        status=status,
        title="召回计划",
        message=message,
        display_payload={
            "original_query": plan.original_query,
            "sub_query_count": len(plan.sub_queries),
            "sub_queries": [
                {
                    "query_id": sub_query.query_id,
                    "channel": sub_query.channel,
                    "domain": sub_query.domain,
                    "purpose": sub_query.purpose,
                    "query_text": sub_query.query_text,
                    "structured_plan": (
                        sub_query.structured_plan.model_dump()
                        if sub_query.structured_plan else None
                    ),
                    "unstructured_plan": (
                        sub_query.unstructured_plan.model_dump()
                        if sub_query.unstructured_plan else None
                    ),
                }
                for sub_query in plan.sub_queries
            ],
            "merge_goal": plan.merge_goal,
        },
    )

