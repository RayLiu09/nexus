from __future__ import annotations

import json

import pytest

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
)
from nexus_app.config import Settings
from nexus_app.retrieval.intent import IntentRecognitionService
from nexus_app.retrieval.prompts import build_intent_recognition_messages
from nexus_app.retrieval.schemas import ContextPackStatus, StepStatus


class _FakeLLMClient:
    def __init__(self, content: str | Exception) -> None:
        self.content = content
        self.calls = []

    def call(
        self,
        model_alias,
        messages,
        *,
        temperature=0.2,
        max_tokens=2048,
        response_format=None,
    ):
        self.calls.append(
            {
                "model_alias": model_alias,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        if isinstance(self.content, Exception):
            raise self.content
        return self.content, LiteLLMCallSummary(
            model_alias=model_alias,
            request_id="intent-test",
            latency_ms=1.0,
            status="success",
            input_hash="hash",
        )


def _settings() -> Settings:
    return Settings(
        DEFAULT_GOVERNANCE_MODEL="governance-model",
        DEFAULT_RETRIEVAL_INTENT_MODEL="intent-model",
        RETRIEVAL_INTENT_CONFIDENCE_THRESHOLD=0.78,
    )


def _intent_payload(**overrides) -> dict:
    payload = {
        "business_domains": ["major_distribution"],
        "retrieval_channels": ["structured"],
        "question_type": "aggregation",
        "output_expectation": ["trend_table", "summary"],
        "constraints": {
            "major_name": "电子商务",
            "education_level": "高职",
            "time_range": [2024, 2026],
        },
        "confidence": 0.91,
    }
    payload.update(overrides)
    return payload


def test_intent_recognition_returns_completed_step_for_high_confidence_output():
    llm = _FakeLLMClient(json.dumps(_intent_payload(), ensure_ascii=False))
    service = IntentRecognitionService(settings=_settings(), llm_client=llm)

    result = service.recognize("近三年高职电子商务专业布点数变化")

    assert result.status == ContextPackStatus.COMPLETED
    assert result.intent is not None
    assert result.intent.business_domains == ["major_distribution"]
    assert result.intent.confidence == pytest.approx(0.91)
    assert result.context_pack is None
    assert result.conversation_step.status == StepStatus.COMPLETED
    assert result.conversation_step.display_payload["confidence"] == pytest.approx(0.91)
    assert llm.calls[0]["model_alias"] == "intent-model"
    assert llm.calls[0]["temperature"] == 0.0
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_intent_recognition_returns_clarification_for_low_confidence_output():
    llm = _FakeLLMClient(
        json.dumps(
            _intent_payload(
                confidence=0.62,
                candidate_intents=[
                    {
                        "business_domain": "major_distribution",
                        "question_type": "aggregation",
                        "confidence": 0.46,
                    }
                ],
                missing_constraints=["专业名称"],
                suggested_refinements=["请补充要查询的专业名称。"],
            ),
            ensure_ascii=False,
        )
    )
    service = IntentRecognitionService(settings=_settings(), llm_client=llm)

    result = service.recognize("帮我查一下趋势")

    assert result.status == ContextPackStatus.NEEDS_CLARIFICATION
    assert result.context_pack is not None
    assert result.context_pack.retrieval_plan is None
    assert result.context_pack.clarification is not None
    assert result.context_pack.clarification.message == (
        "当前问题的检索意图不够清晰，是否愿意进一步优化问题？"
    )
    assert result.context_pack.warnings == ["intent_confidence_below_threshold"]
    assert result.conversation_step.status == StepStatus.NEEDS_CLARIFICATION
    assert result.conversation_step.display_payload["missing_constraints"] == ["专业名称"]


def test_intent_recognition_handles_invalid_json_without_unhandled_exception():
    llm = _FakeLLMClient("not json")
    service = IntentRecognitionService(settings=_settings(), llm_client=llm)

    result = service.recognize("随便查查")

    assert result.status == ContextPackStatus.NEEDS_CLARIFICATION
    assert result.context_pack is not None
    assert result.context_pack.warnings == ["intent_schema_invalid"]
    assert result.conversation_step.status == StepStatus.FAILED
    assert result.intent is not None
    assert result.intent.confidence == 0.0


def test_intent_recognition_handles_schema_invalid_json_safely():
    llm = _FakeLLMClient(json.dumps({"business_domains": ["unknown"], "confidence": 1.2}))
    service = IntentRecognitionService(settings=_settings(), llm_client=llm)

    result = service.recognize("随便查查")

    assert result.status == ContextPackStatus.NEEDS_CLARIFICATION
    assert result.context_pack is not None
    assert result.context_pack.warnings == ["intent_schema_invalid"]
    assert result.conversation_step.status == StepStatus.FAILED


def test_intent_recognition_handles_litellm_call_error_safely():
    llm = _FakeLLMClient(
        LiteLLMCallError("timeout", error_type=LiteLLMErrorType.TIMEOUT)
    )
    service = IntentRecognitionService(settings=_settings(), llm_client=llm)

    result = service.recognize("随便查查")

    assert result.status == ContextPackStatus.NEEDS_CLARIFICATION
    assert result.context_pack is not None
    assert result.context_pack.warnings == ["intent_llm_call_failed"]
    assert result.conversation_step.status == StepStatus.FAILED


def test_intent_prompt_includes_domain_registry_and_no_credentials():
    messages = build_intent_recognition_messages(
        "近三年高职电子商务专业布点数变化",
        confidence_threshold=0.78,
    )

    assert len(messages) == 2
    payload = json.loads(messages[1]["content"])
    domains = {item["domain"] for item in payload["domains"]}
    assert "major_distribution" in domains
    assert "course_textbook" in domains
    assert payload["confidence_threshold"] == 0.78
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "api_key" not in rendered.lower()
    assert "litellm_api_key" not in rendered.lower()

