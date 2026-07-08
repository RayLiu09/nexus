from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_api.api.internal.knowledge_retrieval import (
    get_retrieval_orchestrator,
    get_retrieval_summary_service,
)
from nexus_app.retrieval import (
    ACCESS_SCOPE_ALL_ASSETS,
    Clarification,
    ContextPackStatus,
    ConversationStep,
    ConversationStepName,
    LlmSummary,
    RetrievalChannel,
    RetrievalContextPack,
    RetrievalIntent,
    RetrievalPlan,
    RetrievalResult,
    RetrievalSourceRef,
    RetrievalSubQuery,
    RetrievalSummaryResult,
    StepStatus,
    StructuredAggregation,
    StructuredPlan,
)


class _FakeOrchestrator:
    def __init__(self, context_pack: RetrievalContextPack) -> None:
        self.context_pack = context_pack
        self.calls: list[str] = []
        self.plan_calls: list[str] = []

    def run(self, session, query: str) -> RetrievalContextPack:
        self.calls.append(query)
        return self.context_pack.model_copy(deep=True)

    def plan(self, query: str) -> RetrievalContextPack:
        self.plan_calls.append(query)
        planned = self.context_pack.model_copy(deep=True)
        return planned.model_copy(
            update={
                "status": ContextPackStatus.PLANNED,
                "retrieval_results": [],
                "source_refs": [],
                "llm_summary": None,
            }
        )


class _FakeSummaryService:
    def __init__(self, summary: LlmSummary) -> None:
        self.summary = summary
        self.calls: list[RetrievalContextPack] = []

    def generate(self, context_pack: RetrievalContextPack) -> RetrievalSummaryResult:
        self.calls.append(context_pack)
        return RetrievalSummaryResult(summary=self.summary, warnings=tuple(self.summary.warnings))


def _intent(**overrides) -> RetrievalIntent:
    payload = {
        "business_domains": ["major_distribution"],
        "retrieval_channels": ["structured"],
        "question_type": "aggregation",
        "confidence": 0.92,
    }
    payload.update(overrides)
    return RetrievalIntent.model_validate(payload)


def _structured_sub_query() -> RetrievalSubQuery:
    return RetrievalSubQuery(
        query_id="q1",
        channel=RetrievalChannel.STRUCTURED,
        domain="major_distribution",
        purpose="trend_aggregation",
        query_text="电子商务专业布点趋势",
        structured_plan=StructuredPlan(
            table_profile="major_distribution.v1",
            query_profile="major_distribution.trend_by_year",
            filters={"major_name": "电子商务"},
            group_by=["year"],
        ),
    )


def _completed_pack() -> RetrievalContextPack:
    source = RetrievalSourceRef(
        source_ref_id="q1-src-1",
        channel=RetrievalChannel.STRUCTURED,
        domain="major_distribution",
        asset_id="asset-md",
        asset_version_id="version-md",
        normalized_ref_id="ref-md",
        record_ref="major_distribution_record:record-1",
        locator={"row_range": [2, 2]},
    )
    return RetrievalContextPack(
        status=ContextPackStatus.COMPLETED,
        original_query="近三年高职电子商务专业布点数变化",
        intent=_intent(),
        retrieval_plan=RetrievalPlan(
            original_query="近三年高职电子商务专业布点数变化",
            sub_queries=[_structured_sub_query()],
            merge_goal="生成趋势表和摘要",
        ),
        retrieval_results=[
            RetrievalResult(
                query_id="q1",
                channel=RetrievalChannel.STRUCTURED,
                domain="major_distribution",
                status=StepStatus.COMPLETED,
                result_shape="aggregation",
                aggregations=[
                    StructuredAggregation(
                        group_by=["year"],
                        metric="sum(distribution_count)",
                        series=[{"year": 2026, "value": 16, "record_count": 2}],
                    )
                ],
                source_refs=[source],
            )
        ],
        source_refs=[source],
        conversation_steps=[
            ConversationStep(
                step=ConversationStepName.INTENT_RECOGNITION,
                status=StepStatus.COMPLETED,
                title="意图识别",
            ),
            ConversationStep(
                step=ConversationStepName.QUERY_TRANSFORMATION,
                status=StepStatus.COMPLETED,
                title="召回计划",
            ),
        ],
        access_scope=ACCESS_SCOPE_ALL_ASSETS,
    )


def _clarification_pack() -> RetrievalContextPack:
    intent = _intent(
        business_domains=["course_textbook"],
        retrieval_channels=["unstructured"],
        question_type="unknown",
        confidence=0.62,
        missing_constraints=["数据领域"],
        suggested_refinements=["请补充要查询的数据领域。"],
    )
    return RetrievalContextPack(
        status=ContextPackStatus.NEEDS_CLARIFICATION,
        original_query="帮我查一下",
        intent=intent,
        conversation_steps=[
            ConversationStep(
                step=ConversationStepName.INTENT_RECOGNITION,
                status=StepStatus.NEEDS_CLARIFICATION,
                title="意图识别",
                message="当前问题的检索意图不够清晰，是否愿意进一步优化问题？",
            )
        ],
        clarification=Clarification(
            message="当前问题的检索意图不够清晰，是否愿意进一步优化问题？",
            missing_constraints=["数据领域"],
            suggested_refinements=["请补充要查询的数据领域。"],
        ),
        access_scope=ACCESS_SCOPE_ALL_ASSETS,
        warnings=["intent_confidence_below_threshold"],
    )


def test_knowledge_retrieval_query_returns_completed_context_pack(app) -> None:
    orchestrator = _FakeOrchestrator(_completed_pack())
    summary = LlmSummary(
        content="## 检索结论\n\n- 2026 年布点数为 16。[q1-src-1]",
        source_ref_ids=["q1-src-1"],
        model_alias="summary-model",
    )
    summary_service = _FakeSummaryService(summary)
    app.dependency_overrides[get_retrieval_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_retrieval_summary_service] = lambda: summary_service

    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/knowledge-retrieval/query",
            json={"query": "近三年高职电子商务专业布点数变化"},
        )

    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    assert data["status"] == "completed"
    assert data["access_scope"] == "all_assets"
    assert data["intent"]["business_domains"] == ["major_distribution"]
    assert data["retrieval_plan"]["sub_queries"][0]["query_id"] == "q1"
    assert data["retrieval_results"][0]["aggregations"][0]["series"][0]["value"] == 16
    assert data["source_refs"][0]["source_ref_id"] == "q1-src-1"
    assert data["llm_summary"]["content"] == summary.content
    assert data["markdown"] == summary.content
    assert data["conversation_steps"][-1]["step"] == "summary_generation"
    assert data["conversation_steps"][-1]["status"] == "completed"
    assert body["meta"]["trace_id"]
    assert orchestrator.calls == ["近三年高职电子商务专业布点数变化"]
    assert len(summary_service.calls) == 1


def test_knowledge_retrieval_query_returns_clarification_without_summary(app) -> None:
    orchestrator = _FakeOrchestrator(_clarification_pack())
    summary_service = _FakeSummaryService(LlmSummary(content="should not be used"))
    app.dependency_overrides[get_retrieval_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_retrieval_summary_service] = lambda: summary_service

    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/knowledge-retrieval/query",
            json={"query": "帮我查一下"},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "needs_clarification"
    assert data["retrieval_plan"] is None
    assert data["markdown"] is None
    assert data["clarification"]["missing_constraints"] == ["数据领域"]
    assert data["conversation_steps"][-1]["step"] == "summary_generation"
    assert data["conversation_steps"][-1]["status"] == "skipped"
    assert summary_service.calls == []


def test_knowledge_retrieval_query_can_skip_summary_by_option(app) -> None:
    orchestrator = _FakeOrchestrator(_completed_pack())
    summary_service = _FakeSummaryService(LlmSummary(content="should not be used"))
    app.dependency_overrides[get_retrieval_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_retrieval_summary_service] = lambda: summary_service

    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/knowledge-retrieval/query",
            json={
                "query": "近三年高职电子商务专业布点数变化",
                "options": {"enable_llm_summary": False},
            },
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["llm_summary"] is None
    assert data["markdown"] is None
    assert data["conversation_steps"][-1]["status"] == "skipped"
    assert summary_service.calls == []


def test_knowledge_retrieval_plans_returns_plan_without_results_or_summary(app) -> None:
    orchestrator = _FakeOrchestrator(_completed_pack())
    app.dependency_overrides[get_retrieval_orchestrator] = lambda: orchestrator

    with TestClient(app) as client:
        resp = client.post(
            "/internal/v1/knowledge-retrieval/plans",
            json={"query": "近三年高职电子商务专业布点数变化"},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "planned"
    assert data["intent"]["confidence"] == 0.92
    assert data["retrieval_plan"]["sub_queries"][0]["structured_plan"]["table_profile"] == (
        "major_distribution.v1"
    )
    assert data["retrieval_results"] == []
    assert data["source_refs"] == []
    assert data["llm_summary"] is None
    assert data["markdown"] is None
    assert orchestrator.calls == []
    assert orchestrator.plan_calls == ["近三年高职电子商务专业布点数变化"]


def test_knowledge_retrieval_query_validates_query_body(app) -> None:
    with TestClient(app) as client:
        resp = client.post("/internal/v1/knowledge-retrieval/query", json={"query": ""})

    assert resp.status_code == 422
