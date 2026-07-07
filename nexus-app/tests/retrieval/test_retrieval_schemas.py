from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus_app.retrieval.schemas import (
    ACCESS_SCOPE_ALL_ASSETS,
    INTENT_CONFIDENCE_THRESHOLD,
    BusinessDomain,
    CandidateIntent,
    Clarification,
    ContextPackStatus,
    ConversationStep,
    ConversationStepName,
    QueryMetric,
    QueryOrder,
    RetrievalChannel,
    RetrievalContextPack,
    RetrievalIntent,
    RetrievalPlan,
    RetrievalResult,
    RetrievalSourceRef,
    RetrievalSubQuery,
    StepStatus,
    StructuredAggregation,
    StructuredPlan,
    UnstructuredPlan,
    UnstructuredResultItem,
)


def test_high_confidence_intent_is_valid_without_clarification():
    intent = RetrievalIntent(
        business_domains=[BusinessDomain.MAJOR_DISTRIBUTION],
        retrieval_channels=[RetrievalChannel.STRUCTURED],
        question_type="aggregation",
        output_expectation=["trend_table", "summary", "summary"],
        constraints={"major_name": "电子商务"},
        confidence=0.91,
    )

    assert intent.confidence_threshold == INTENT_CONFIDENCE_THRESHOLD
    assert intent.needs_clarification is False
    assert intent.output_expectation == ["trend_table", "summary"]


def test_low_confidence_intent_keeps_clarification_payload():
    intent = RetrievalIntent(
        business_domains=[BusinessDomain.MAJOR_DISTRIBUTION],
        retrieval_channels=[RetrievalChannel.STRUCTURED],
        question_type="aggregation",
        confidence=0.62,
        candidate_intents=[
            CandidateIntent(
                business_domain=BusinessDomain.MAJOR_PROFILE,
                question_type="knowledge_lookup",
                confidence=0.44,
            )
        ],
        missing_constraints=["数据领域"],
        suggested_refinements=["请补充专业名称"],
    )

    assert intent.needs_clarification is True
    assert intent.candidate_intents[0].business_domain == "major_profile"
    assert intent.suggested_refinements == ["请补充专业名称"]


def test_hybrid_retrieval_plan_validates_structured_and_unstructured_sub_queries():
    plan = RetrievalPlan(
        original_query="近三年高职电子商务专业布点数变化，并说明相关专业简介依据",
        sub_queries=[
            RetrievalSubQuery(
                query_id="q1",
                channel=RetrievalChannel.STRUCTURED,
                domain=BusinessDomain.MAJOR_DISTRIBUTION,
                purpose="trend_aggregation",
                query_text="高职电子商务专业 2024-2026 布点数",
                structured_plan=StructuredPlan(
                    table_profile="major_distribution.v1",
                    query_profile="major_distribution.trend_by_year",
                    filters={"major_name": "电子商务", "education_level": "高职"},
                    group_by=["year"],
                    metrics=[QueryMetric(field="distribution_count", function="sum")],
                    order_by=[QueryOrder(field="year", direction="asc")],
                ),
            ),
            RetrievalSubQuery(
                query_id="q2",
                channel=RetrievalChannel.UNSTRUCTURED,
                domain=BusinessDomain.MAJOR_PROFILE,
                purpose="supporting_evidence",
                query_text="电子商务专业 简介 职业面向 核心课程",
                unstructured_plan=UnstructuredPlan(
                    top_k=8,
                    filters={"classification": ["major_profile"]},
                    query_terms=["电子商务", "职业面向"],
                ),
            ),
        ],
        merge_goal="生成趋势表和专业简介依据",
    )

    assert len(plan.sub_queries) == 2
    assert plan.sub_queries[0].structured_plan.table_profile == "major_distribution.v1"
    assert plan.sub_queries[1].unstructured_plan.top_k == 8


def test_structured_plan_rejects_raw_sql_extra_field():
    with pytest.raises(ValidationError):
        StructuredPlan(
            table_profile="major_distribution.v1",
            raw_sql="select * from major_distribution_record",
        )


def test_sub_query_requires_plan_matching_channel():
    with pytest.raises(ValidationError, match="structured_plan"):
        RetrievalSubQuery(
            query_id="q1",
            channel=RetrievalChannel.STRUCTURED,
            domain=BusinessDomain.MAJOR_DISTRIBUTION,
            purpose="trend_aggregation",
            query_text="高职电子商务专业布点数",
        )


def test_context_pack_defaults_to_all_assets_and_holds_results():
    intent = RetrievalIntent(
        business_domains=[BusinessDomain.COURSE_TEXTBOOK],
        retrieval_channels=[RetrievalChannel.UNSTRUCTURED],
        question_type="definition",
        confidence=0.88,
    )
    plan = RetrievalPlan(
        original_query="什么是直播电商？",
        sub_queries=[
            RetrievalSubQuery(
                query_id="q1",
                channel=RetrievalChannel.UNSTRUCTURED,
                domain=BusinessDomain.COURSE_TEXTBOOK,
                purpose="definition_lookup",
                query_text="直播电商 定义 概念",
                unstructured_plan=UnstructuredPlan(top_k=5),
            )
        ],
    )
    source = RetrievalSourceRef(
        source_ref_id="src-1",
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        normalized_ref_id="ref-1",
        chunk_id="chunk-1",
        locator={"page_start": 1},
        score=0.83,
    )
    result = RetrievalResult(
        query_id="q1",
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        items=[
            UnstructuredResultItem(
                result_id="r1",
                chunk_id="chunk-1",
                normalized_ref_id="ref-1",
                score=0.83,
                content_preview="直播电商是...",
                source_ref_id="src-1",
            )
        ],
        source_refs=[source],
    )

    pack = RetrievalContextPack(
        status=ContextPackStatus.COMPLETED,
        original_query="什么是直播电商？",
        intent=intent,
        retrieval_plan=plan,
        retrieval_results=[result],
        source_refs=[source],
        conversation_steps=[
            ConversationStep(
                step=ConversationStepName.INTENT_RECOGNITION,
                status=StepStatus.COMPLETED,
                title="意图识别",
                display_payload={"confidence": 0.88},
            )
        ],
    )

    assert pack.access_scope == ACCESS_SCOPE_ALL_ASSETS
    assert pack.retrieval_results[0].items[0].chunk_id == "chunk-1"
    assert pack.conversation_steps[0].display_to_user is True


def test_context_pack_needs_clarification_requires_clarification_payload():
    intent = RetrievalIntent(
        business_domains=[BusinessDomain.MAJOR_PROFILE],
        retrieval_channels=[RetrievalChannel.UNSTRUCTURED],
        question_type="knowledge_lookup",
        confidence=0.42,
    )

    with pytest.raises(ValidationError, match="clarification"):
        RetrievalContextPack(
            status=ContextPackStatus.NEEDS_CLARIFICATION,
            original_query="帮我查一下",
            intent=intent,
        )

    pack = RetrievalContextPack(
        status=ContextPackStatus.NEEDS_CLARIFICATION,
        original_query="帮我查一下",
        intent=intent,
        clarification=Clarification(
            message="当前问题的检索意图不够清晰，是否愿意进一步优化问题？",
            suggested_refinements=["请补充数据领域"],
        ),
        warnings=["intent_confidence_below_threshold"],
    )

    assert pack.clarification.message.startswith("当前问题")
    assert pack.warnings == ["intent_confidence_below_threshold"]


def test_structured_result_supports_aggregation_and_source_refs():
    result = RetrievalResult(
        query_id="q1",
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        result_shape="aggregation",
        aggregations=[
            StructuredAggregation(
                group_by=["year"],
                metric="sum(distribution_count)",
                series=[{"year": 2024, "value": 32}],
            )
        ],
        source_refs=[
            RetrievalSourceRef(
                source_ref_id="src-md-1",
                channel=RetrievalChannel.STRUCTURED,
                domain=BusinessDomain.MAJOR_DISTRIBUTION,
                asset_version_id="version-1",
                normalized_ref_id="ref-1",
                record_ref="major_distribution_record:rec-1",
                locator={"row_range": [2, 180]},
            )
        ],
    )

    assert result.aggregations[0].series[0]["value"] == 32
    assert result.source_refs[0].record_ref == "major_distribution_record:rec-1"

