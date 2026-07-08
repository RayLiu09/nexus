"""LiteLLM-backed retrieval plan generation."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

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


class RetrievalPlanParseError(ValueError):
    """Schema failure with safe diagnostics for Console observability."""

    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


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
        except RetrievalPlanParseError as exc:
            logger.warning(
                "retrieval planner output invalid model_alias=%s request_id=%s",
                self._model_alias,
                summary.request_id,
            )
            return self._failed_result(
                "retrieval_plan_schema_invalid",
                diagnostics=exc.diagnostics,
            )

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
            raise RetrievalPlanParseError(
                "retrieval plan output is not valid JSON",
                {
                    "failure_type": "invalid_json",
                    "raw_shape": "non_json",
                },
            ) from exc
        if not isinstance(payload, dict):
            raise RetrievalPlanParseError(
                "retrieval plan output must be a JSON object",
                _plan_diagnostics(payload, validation_error=None),
            )
        payload.setdefault("original_query", fallback_query)
        try:
            return RetrievalPlan.model_validate(payload)
        except ValidationError as exc:
            raise RetrievalPlanParseError(
                "retrieval plan output does not match RetrievalPlan schema",
                _plan_diagnostics(payload, validation_error=exc),
            ) from exc

    def _failed_result(
        self,
        reason: str,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> RetrievalPlannerResult:
        return RetrievalPlannerResult(
            plan=None,
            conversation_step=ConversationStep(
                step=ConversationStepName.QUERY_TRANSFORMATION,
                status=StepStatus.FAILED,
                title="召回计划",
                message="召回计划无法通过 schema 校验，未执行检索。",
                display_payload={
                    "reason": reason,
                    "diagnostics": diagnostics or {},
                },
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


def _plan_diagnostics(
    payload: Any,
    *,
    validation_error: ValidationError | None,
) -> dict[str, Any]:
    """Build non-sensitive diagnostics for invalid planner output.

    The diagnostics intentionally avoid returning raw LLM text, prompt text,
    query_text values, filters, or source content. They only expose structural
    metadata needed to debug schema mismatch in Console.
    """

    diagnostics: dict[str, Any] = {
        "raw_shape": _json_shape(payload),
    }
    if isinstance(payload, list):
        diagnostics["item_count"] = len(payload)
        diagnostics["failure_type"] = (
            "intent_candidates_returned_instead_of_plan"
            if _looks_like_candidate_intent_list(payload)
            else "top_level_array"
        )
        diagnostics["required_top_level_shape"] = "object"
        diagnostics["required_top_level_fields"] = ["original_query", "sub_queries", "merge_goal"]
        if payload and isinstance(payload[0], dict):
            diagnostics["first_item_keys"] = sorted(str(key) for key in payload[0].keys())
        return diagnostics

    if not isinstance(payload, dict):
        diagnostics["failure_type"] = "top_level_not_object"
        diagnostics["required_top_level_shape"] = "object"
        return diagnostics

    top_level_keys = sorted(str(key) for key in payload.keys())
    diagnostics["top_level_keys"] = top_level_keys
    missing = [
        field
        for field in ("original_query", "sub_queries")
        if field not in payload or payload.get(field) in (None, "")
    ]
    if missing:
        diagnostics["missing_top_level_fields"] = missing

    sub_queries = payload.get("sub_queries")
    if isinstance(sub_queries, list):
        diagnostics["sub_query_count"] = len(sub_queries)
        diagnostics["sub_query_shapes"] = [
            _sub_query_shape(item)
            for item in sub_queries[:5]
            if isinstance(item, dict)
        ]
    elif "sub_queries" in payload:
        diagnostics["sub_queries_shape"] = _json_shape(sub_queries)

    unsafe_fields = sorted(_find_unsafe_field_names(payload))
    if unsafe_fields:
        diagnostics["unsafe_field_names"] = unsafe_fields

    if _looks_like_intent_payload(payload):
        diagnostics["failure_type"] = "intent_payload_returned_instead_of_plan"

    if validation_error is not None:
        errors = validation_error.errors()
        diagnostics["validation_error_count"] = len(errors)
        diagnostics["validation_errors"] = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": error.get("type"),
                "msg": error.get("msg"),
            }
            for error in errors[:8]
        ]
        diagnostics.setdefault("failure_type", _classify_validation_errors(errors))

    return diagnostics


def _json_shape(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return type(value).__name__


def _looks_like_candidate_intent_list(value: list[Any]) -> bool:
    if not value:
        return False
    candidates = [item for item in value if isinstance(item, dict)]
    if not candidates:
        return False
    return all(_looks_like_candidate_intent(item) for item in candidates)


def _looks_like_candidate_intent(value: dict[Any, Any]) -> bool:
    keys = {str(key) for key in value}
    return {"business_domain", "question_type", "confidence"}.issubset(keys)


def _looks_like_intent_payload(value: dict[Any, Any]) -> bool:
    keys = {str(key) for key in value}
    return "business_domains" in keys and "confidence" in keys and "sub_queries" not in keys


def _sub_query_shape(value: dict[Any, Any]) -> dict[str, Any]:
    keys = {str(key) for key in value}
    channel = value.get("channel")
    shape: dict[str, Any] = {
        "keys": sorted(keys),
        "channel": channel if isinstance(channel, str) else _json_shape(channel),
        "domain": value.get("domain") if isinstance(value.get("domain"), str) else _json_shape(value.get("domain")),
        "has_structured_plan": "structured_plan" in keys and value.get("structured_plan") is not None,
        "has_unstructured_plan": "unstructured_plan" in keys and value.get("unstructured_plan") is not None,
        "has_query_text": bool(value.get("query_text")),
    }
    if channel == "structured" and not shape["has_structured_plan"]:
        shape["plan_mismatch"] = "structured_channel_requires_structured_plan"
    if channel == "unstructured" and not shape["has_unstructured_plan"]:
        shape["plan_mismatch"] = "unstructured_channel_requires_unstructured_plan"
    return shape


def _find_unsafe_field_names(value: Any) -> set[str]:
    unsafe = {"sql", "raw_sql", "ddl", "dml"}
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            if key_str.lower() in unsafe:
                found.add(key_str)
            found.update(_find_unsafe_field_names(child))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_unsafe_field_names(item))
    return found


def _classify_validation_errors(errors: list[dict[str, Any]]) -> str:
    locations = [".".join(str(part) for part in error.get("loc", ())) for error in errors]
    if any(error.get("type") == "extra_forbidden" for error in errors):
        return "extra_fields_forbidden"
    if any(error.get("type") == "missing" for error in errors):
        return "required_fields_missing"
    messages = [str(error.get("msg", "")) for error in errors]
    if any("requires structured_plan" in message for message in messages):
        return "channel_plan_mismatch"
    if any("requires unstructured_plan" in message for message in messages):
        return "channel_plan_mismatch"
    if any("sub_queries" in location and "structured_plan" in location for location in locations):
        return "structured_plan_invalid"
    if any("sub_queries" in location and "unstructured_plan" in location for location in locations):
        return "unstructured_plan_invalid"
    return "schema_validation_failed"
