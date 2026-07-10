from __future__ import annotations

import json

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
)
from nexus_app.config import Settings
from nexus_app.retrieval.planner import RetrievalPlannerService
from nexus_app.retrieval.prompts import build_retrieval_plan_messages
from nexus_app.retrieval.schemas import RetrievalIntent, StepStatus


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
            request_id="planner-test",
            latency_ms=1.0,
            status="success",
            input_hash="hash",
        )


def _settings() -> Settings:
    return Settings(
        DEFAULT_GOVERNANCE_MODEL="governance-model",
        DEFAULT_RETRIEVAL_PLANNER_MODEL="planner-model",
        RETRIEVAL_MAX_SUB_QUERIES=5,
    )


def _intent(**overrides) -> RetrievalIntent:
    payload = {
        "business_domains": ["course_textbook"],
        "retrieval_channels": ["unstructured"],
        "question_type": "definition",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return RetrievalIntent.model_validate(payload)


def _plan_payload(sub_queries, **overrides) -> dict:
    payload = {
        "original_query": "什么是直播电商？",
        "sub_queries": sub_queries,
        "merge_goal": "生成定义解释和来源引用",
    }
    payload.update(overrides)
    return payload


def test_planner_returns_single_unstructured_plan():
    llm = _FakeLLMClient(
        json.dumps(
            _plan_payload(
                [
                    {
                        "query_id": "q1",
                        "channel": "unstructured",
                        "domain": "course_textbook",
                        "purpose": "definition_lookup",
                        "query_text": "直播电商 定义 概念 特征",
                        "unstructured_plan": {
                            "top_k": 8,
                            "filters": {"classification": ["course_textbook"]},
                            "query_terms": ["直播电商", "定义"],
                        },
                    }
                ]
            ),
            ensure_ascii=False,
        )
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("什么是直播电商？", _intent())

    assert result.success is True
    assert result.plan is not None
    assert result.plan.sub_queries[0].channel == "unstructured"
    assert result.plan.sub_queries[0].unstructured_plan.top_k == 8
    assert result.conversation_step.status == StepStatus.COMPLETED
    assert result.conversation_step.display_payload["sub_query_count"] == 1
    assert llm.calls[0]["model_alias"] == "planner-model"
    assert llm.calls[0]["temperature"] == 0.0
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_planner_returns_major_distribution_structured_plan_without_sql():
    intent = _intent(
        business_domains=["major_distribution"],
        retrieval_channels=["structured"],
        question_type="aggregation",
        constraints={"major_name": "电子商务", "education_level": "高职"},
    )
    llm = _FakeLLMClient(
        json.dumps(
            _plan_payload(
                [
                    {
                        "query_id": "q1",
                        "channel": "structured",
                        "domain": "major_distribution",
                        "purpose": "trend_aggregation",
                        "query_text": "高职电子商务专业 2024-2026 布点数年度变化",
                        "structured_plan": {
                            "table_profile": "major_distribution.v1",
                            "query_profile": "major_distribution.trend_by_year",
                            "filters": {
                                "major_name": "电子商务",
                                "education_level": "高职",
                                "year_between": [2024, 2026],
                            },
                            "group_by": ["year"],
                            "metrics": [
                                {"field": "distribution_count", "function": "sum"}
                            ],
                            "order_by": [{"field": "year", "direction": "asc"}],
                            "limit": 50,
                        },
                    }
                ],
                original_query="近三年高职电子商务专业布点数变化",
                merge_goal="生成趋势表和摘要",
            ),
            ensure_ascii=False,
        )
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("近三年高职电子商务专业布点数变化", intent)

    assert result.success is True
    assert result.plan is not None
    structured = result.plan.sub_queries[0].structured_plan
    assert structured.table_profile == "major_distribution.v1"
    assert structured.query_profile == "major_distribution.trend_by_year"
    assert "raw_sql" not in structured.model_dump()
    assert result.conversation_step.display_payload["sub_queries"][0]["structured_plan"][
        "group_by"
    ] == ["year"]


def test_planner_returns_hybrid_plan_with_merge_goal():
    intent = _intent(
        business_domains=["major_distribution", "major_profile"],
        retrieval_channels=["structured", "unstructured"],
        question_type="comparison",
        confidence=0.88,
    )
    llm = _FakeLLMClient(
        json.dumps(
            _plan_payload(
                [
                    {
                        "query_id": "q1",
                        "channel": "structured",
                        "domain": "major_distribution",
                        "purpose": "trend_aggregation",
                        "query_text": "电子商务专业布点趋势",
                        "structured_plan": {
                            "table_profile": "major_distribution.v1",
                            "query_profile": "major_distribution.trend_by_year",
                            "filters": {"major_name": "电子商务"},
                            "group_by": ["year"],
                            "metrics": [
                                {"field": "distribution_count", "function": "sum"}
                            ],
                            "order_by": [{"field": "year", "direction": "asc"}],
                        },
                    },
                    {
                        "query_id": "q2",
                        "channel": "unstructured",
                        "domain": "major_profile",
                        "purpose": "supporting_evidence",
                        "query_text": "电子商务专业 简介 职业面向 核心课程",
                        "unstructured_plan": {"top_k": 8, "filters": {}, "query_terms": []},
                    },
                ],
                merge_goal="生成趋势表、解释摘要和来源引用",
            ),
            ensure_ascii=False,
        )
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("电子商务专业布点增长是否有专业简介依据？", intent)

    assert result.success is True
    assert result.plan is not None
    assert len(result.plan.sub_queries) == 2
    assert result.plan.merge_goal == "生成趋势表、解释摘要和来源引用"


def test_planner_fails_safely_when_output_exceeds_max_sub_queries():
    sub_queries = [
        {
            "query_id": f"q{i}",
            "channel": "unstructured",
            "domain": "course_textbook",
            "purpose": "lookup",
            "query_text": f"查询 {i}",
            "unstructured_plan": {"top_k": 3},
        }
        # v1.3 R3 raised MAX_SUB_QUERIES_V1_3 to 8; 9 sub_queries now
        # trips the same schema cap that 6 used to trip against the
        # pre-v1.3 MAX_SUB_QUERIES=5.
        for i in range(1, 10)
    ]
    llm = _FakeLLMClient(json.dumps(_plan_payload(sub_queries), ensure_ascii=False))
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("复合问题", _intent())

    assert result.success is False
    assert result.plan is None
    assert result.conversation_step.status == StepStatus.FAILED
    assert result.warnings == ("retrieval_plan_schema_invalid",)
    diagnostics = result.conversation_step.display_payload["diagnostics"]
    assert diagnostics["failure_type"] == "schema_validation_failed"
    assert diagnostics["sub_query_count"] == 9
    assert diagnostics["validation_error_count"] >= 1


def test_planner_reports_candidate_intent_array_misoutput():
    llm = _FakeLLMClient(
        json.dumps(
            [
                {
                    "business_domain": "course_textbook",
                    "question_type": "definition",
                    "confidence": 0.82,
                },
                {
                    "business_domain": "major_profile",
                    "question_type": "definition",
                    "confidence": 0.42,
                },
            ],
            ensure_ascii=False,
        )
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("什么是直播电商？", _intent())

    assert result.success is False
    assert result.warnings == ("retrieval_plan_schema_invalid",)
    diagnostics = result.conversation_step.display_payload["diagnostics"]
    assert diagnostics["failure_type"] == "intent_candidates_returned_instead_of_plan"
    assert diagnostics["raw_shape"] == "array"
    assert diagnostics["item_count"] == 2
    assert diagnostics["required_top_level_shape"] == "object"
    assert diagnostics["first_item_keys"] == [
        "business_domain",
        "confidence",
        "question_type",
    ]


def test_planner_reports_intent_payload_misoutput():
    llm = _FakeLLMClient(
        json.dumps(
            {
                "business_domains": ["course_textbook"],
                "retrieval_channels": ["unstructured"],
                "question_type": "definition",
                "confidence": 0.82,
            },
            ensure_ascii=False,
        )
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("什么是直播电商？", _intent())

    assert result.success is False
    diagnostics = result.conversation_step.display_payload["diagnostics"]
    assert diagnostics["failure_type"] == "intent_payload_returned_instead_of_plan"
    assert diagnostics["missing_top_level_fields"] == ["sub_queries"]


def test_planner_reports_channel_plan_mismatch():
    llm = _FakeLLMClient(
        json.dumps(
            _plan_payload(
                [
                    {
                        "query_id": "q1",
                        "channel": "unstructured",
                        "domain": "course_textbook",
                        "purpose": "definition_lookup",
                        "query_text": "直播电商 定义",
                    }
                ]
            ),
            ensure_ascii=False,
        )
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("什么是直播电商？", _intent())

    assert result.success is False
    diagnostics = result.conversation_step.display_payload["diagnostics"]
    assert diagnostics["failure_type"] == "channel_plan_mismatch"
    assert diagnostics["sub_query_shapes"][0]["plan_mismatch"] == (
        "unstructured_channel_requires_unstructured_plan"
    )


def test_planner_fails_safely_when_structured_plan_contains_raw_sql():
    llm = _FakeLLMClient(
        json.dumps(
            _plan_payload(
                [
                    {
                        "query_id": "q1",
                        "channel": "structured",
                        "domain": "major_distribution",
                        "purpose": "unsafe",
                        "query_text": "查询",
                        "structured_plan": {
                            "table_profile": "major_distribution.v1",
                            "raw_sql": "select * from major_distribution_record",
                        },
                    }
                ]
            ),
            ensure_ascii=False,
        )
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("查询", _intent())

    assert result.success is False
    assert result.plan is None
    assert result.conversation_step.status == StepStatus.FAILED
    assert result.warnings == ("retrieval_plan_schema_invalid",)
    diagnostics = result.conversation_step.display_payload["diagnostics"]
    assert diagnostics["failure_type"] == "extra_fields_forbidden"
    assert diagnostics["unsafe_field_names"] == ["raw_sql"]


def test_planner_handles_litellm_call_error_safely():
    llm = _FakeLLMClient(
        LiteLLMCallError("timeout", error_type=LiteLLMErrorType.TIMEOUT)
    )
    service = RetrievalPlannerService(settings=_settings(), llm_client=llm)

    result = service.generate_plan("查询", _intent())

    assert result.success is False
    assert result.plan is None
    assert result.conversation_step.status == StepStatus.FAILED
    assert result.warnings == ("retrieval_plan_llm_call_failed",)


def test_retrieval_plan_prompt_contains_registry_and_no_credentials():
    messages = build_retrieval_plan_messages(
        "近三年高职电子商务专业布点数变化",
        _intent(
            business_domains=["major_distribution"],
            retrieval_channels=["structured"],
            question_type="aggregation",
        ),
    )

    payload = json.loads(messages[1]["content"])
    assert payload["max_sub_queries"] == 5
    domains = {item["domain"] for item in payload["domains"]}
    assert "major_distribution" in domains
    assert "job_demand" in domains
    rendered = json.dumps(payload, ensure_ascii=False).lower()
    assert "api_key" not in rendered
    assert "litellm_api_key" not in rendered
    assert "raw_sql" in rendered
    assert "candidate_intents" in rendered
    assert "top-level output must be a json object" in rendered
