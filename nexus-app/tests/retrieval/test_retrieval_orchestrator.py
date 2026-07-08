from __future__ import annotations

from dataclasses import dataclass

import pytest

from nexus_app.retrieval.intent import IntentRecognitionResult
from nexus_app.retrieval.orchestrator import RetrievalOrchestrator
from nexus_app.retrieval.planner import RetrievalPlannerResult
from nexus_app.retrieval.schemas import (
    ACCESS_SCOPE_ALL_ASSETS,
    BusinessDomain,
    Clarification,
    ContextPackStatus,
    ConversationStep,
    ConversationStepName,
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


class _FakeIntentService:
    def __init__(self, result: IntentRecognitionResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def recognize(self, query: str) -> IntentRecognitionResult:
        self.calls.append(query)
        return self.result


class _FakePlannerService:
    def __init__(self, result: RetrievalPlannerResult) -> None:
        self.result = result
        self.calls: list[tuple[str, RetrievalIntent]] = []

    def generate_plan(
        self,
        query: str,
        intent: RetrievalIntent,
    ) -> RetrievalPlannerResult:
        self.calls.append((query, intent))
        return self.result


class _FakeExecutor:
    def __init__(self, results: dict[str, RetrievalResult] | None = None) -> None:
        self.results = results or {}
        self.calls: list[RetrievalSubQuery] = []

    def execute(self, session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        self.calls.append(sub_query)
        result = self.results.get(sub_query.query_id)
        if result is None:
            raise AssertionError(f"unexpected sub query {sub_query.query_id}")
        return result


class _FailingExecutor:
    def __init__(self) -> None:
        self.calls: list[RetrievalSubQuery] = []

    def execute(self, session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        self.calls.append(sub_query)
        raise RuntimeError("backend unavailable")


@dataclass(frozen=True)
class _Harness:
    orchestrator: RetrievalOrchestrator
    intent_service: _FakeIntentService
    planner_service: _FakePlannerService
    unstructured_executor: _FakeExecutor | _FailingExecutor
    major_distribution_executor: _FakeExecutor | _FailingExecutor
    job_demand_executor: _FakeExecutor | _FailingExecutor
    competency_executor: _FakeExecutor | _FailingExecutor


def _intent(**overrides) -> RetrievalIntent:
    payload = {
        "business_domains": ["course_textbook"],
        "retrieval_channels": ["unstructured"],
        "question_type": "definition",
        "confidence": 0.91,
    }
    payload.update(overrides)
    return RetrievalIntent.model_validate(payload)


def _intent_step(intent: RetrievalIntent) -> ConversationStep:
    return ConversationStep(
        step=ConversationStepName.INTENT_RECOGNITION,
        status=StepStatus.COMPLETED,
        title="意图识别",
        message="意图识别完成",
        display_payload={
            "business_domains": intent.business_domains,
            "retrieval_channels": intent.retrieval_channels,
            "confidence": intent.confidence,
        },
    )


def _plan_step(plan: RetrievalPlan) -> ConversationStep:
    return ConversationStep(
        step=ConversationStepName.QUERY_TRANSFORMATION,
        status=StepStatus.COMPLETED,
        title="召回计划",
        message="召回计划生成完成",
        display_payload={"sub_query_count": len(plan.sub_queries)},
    )


def _unstructured_sub_query(query_id: str = "q1") -> RetrievalSubQuery:
    return RetrievalSubQuery(
        query_id=query_id,
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        purpose="definition_lookup",
        query_text="直播电商 定义",
        unstructured_plan=UnstructuredPlan(top_k=3),
    )


def _structured_sub_query(query_id: str = "q1") -> RetrievalSubQuery:
    return RetrievalSubQuery(
        query_id=query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        purpose="trend_aggregation",
        query_text="电子商务专业布点趋势",
        structured_plan=StructuredPlan(
            table_profile="major_distribution.v1",
            query_profile="major_distribution.trend_by_year",
            filters={"major_name": "电子商务"},
            group_by=["year"],
        ),
    )


def _domain_structured_sub_query(
    *,
    query_id: str,
    domain: BusinessDomain,
    table_profile: str,
    query_profile: str,
) -> RetrievalSubQuery:
    return RetrievalSubQuery(
        query_id=query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=domain,
        purpose="structured_query",
        query_text="结构化查询",
        structured_plan=StructuredPlan(
            table_profile=table_profile,
            query_profile=query_profile,
        ),
    )


def _plan(*sub_queries: RetrievalSubQuery) -> RetrievalPlan:
    return RetrievalPlan(
        original_query="查询",
        sub_queries=list(sub_queries),
        merge_goal="生成结构化检索结果",
    )


def _unstructured_result(query_id: str = "q1") -> RetrievalResult:
    source = RetrievalSourceRef(
        source_ref_id=f"{query_id}-src-1",
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        asset_id="asset-1",
        asset_version_id="version-1",
        normalized_ref_id="ref-1",
        chunk_id="chunk-1",
        score=0.92,
        locator={"page_start": 2},
    )
    return RetrievalResult(
        query_id=query_id,
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        status=StepStatus.COMPLETED,
        result_shape="chunk_hits",
        items=[
            UnstructuredResultItem(
                result_id=f"{query_id}-r-1",
                chunk_id="chunk-1",
                normalized_ref_id="ref-1",
                asset_id="asset-1",
                asset_version_id="version-1",
                score=0.92,
                content_preview="直播电商是通过直播场景完成商品讲解和交易转化。",
                source_ref_id=source.source_ref_id,
            )
        ],
        source_refs=[source],
    )


def _structured_result(query_id: str = "q1") -> RetrievalResult:
    source = RetrievalSourceRef(
        source_ref_id=f"{query_id}-src-1",
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        asset_id="asset-md",
        asset_version_id="version-md",
        normalized_ref_id="ref-md",
        record_ref="major_distribution_record:record-1",
        locator={"row_range": [2, 2]},
    )
    return RetrievalResult(
        query_id=query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
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


def _domain_structured_result(query_id: str, domain: BusinessDomain) -> RetrievalResult:
    source = RetrievalSourceRef(
        source_ref_id=f"{query_id}-src-1",
        channel=RetrievalChannel.STRUCTURED,
        domain=domain,
        normalized_ref_id=f"ref-{query_id}",
        record_ref=f"{domain}:record-1",
    )
    return RetrievalResult(
        query_id=query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=domain,
        status=StepStatus.COMPLETED,
        result_shape="record_list",
        records=[{"id": f"record-{query_id}"}],
        source_refs=[source],
    )


def _harness(
    *,
    intent: RetrievalIntent,
    plan: RetrievalPlan,
    unstructured_results: dict[str, RetrievalResult] | None = None,
    structured_results: dict[str, RetrievalResult] | None = None,
    unstructured_executor=None,
    major_distribution_executor=None,
    job_demand_executor=None,
    competency_executor=None,
) -> _Harness:
    intent_service = _FakeIntentService(
        IntentRecognitionResult(
            status=ContextPackStatus.COMPLETED,
            intent=intent,
            conversation_step=_intent_step(intent),
        )
    )
    planner_service = _FakePlannerService(
        RetrievalPlannerResult(
            plan=plan,
            conversation_step=_plan_step(plan),
        )
    )
    unstructured = unstructured_executor or _FakeExecutor(unstructured_results)
    structured = major_distribution_executor or _FakeExecutor(structured_results)
    job_demand = job_demand_executor or _FakeExecutor(structured_results)
    competency = competency_executor or _FakeExecutor(structured_results)
    return _Harness(
        orchestrator=RetrievalOrchestrator(
            intent_service=intent_service,
            planner_service=planner_service,
            unstructured_executor=unstructured,
            major_distribution_executor=structured,
            job_demand_executor=job_demand,
            competency_executor=competency,
        ),
        intent_service=intent_service,
        planner_service=planner_service,
        unstructured_executor=unstructured,
        major_distribution_executor=structured,
        job_demand_executor=job_demand,
        competency_executor=competency,
    )


def test_orchestrator_returns_clarification_without_planning_or_retrieval(session):
    intent = _intent(confidence=0.62, missing_constraints=["专业名称"])
    clarification_pack = RetrievalContextPack(
        status=ContextPackStatus.NEEDS_CLARIFICATION,
        original_query="帮我查一下趋势",
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
            missing_constraints=["专业名称"],
        ),
        access_scope=ACCESS_SCOPE_ALL_ASSETS,
        warnings=["intent_confidence_below_threshold"],
    )
    intent_service = _FakeIntentService(
        IntentRecognitionResult(
            status=ContextPackStatus.NEEDS_CLARIFICATION,
            intent=intent,
            conversation_step=clarification_pack.conversation_steps[0],
            context_pack=clarification_pack,
        )
    )
    planner_service = _FakePlannerService(
        RetrievalPlannerResult(
            plan=_plan(_unstructured_sub_query()),
            conversation_step=ConversationStep(
                step=ConversationStepName.QUERY_TRANSFORMATION,
                status=StepStatus.COMPLETED,
                title="召回计划",
            ),
        )
    )
    executor = _FakeExecutor({"q1": _unstructured_result()})
    orchestrator = RetrievalOrchestrator(
        intent_service=intent_service,
        planner_service=planner_service,
        unstructured_executor=executor,
        major_distribution_executor=_FakeExecutor({}),
    )

    pack = orchestrator.run(session, "帮我查一下趋势")

    assert pack.status == ContextPackStatus.NEEDS_CLARIFICATION
    assert pack.retrieval_plan is None
    assert pack.clarification is not None
    assert planner_service.calls == []
    assert executor.calls == []


def test_orchestrator_completes_single_unstructured_query(session):
    sub_query = _unstructured_sub_query()
    intent = _intent()
    harness = _harness(
        intent=intent,
        plan=_plan(sub_query),
        unstructured_results={"q1": _unstructured_result()},
        structured_results={},
    )

    pack = harness.orchestrator.run(session, "什么是直播电商？")

    assert pack.status == ContextPackStatus.COMPLETED
    assert pack.access_scope == ACCESS_SCOPE_ALL_ASSETS
    assert pack.intent == intent
    assert pack.retrieval_plan is not None
    assert pack.retrieval_results[0].result_shape == "chunk_hits"
    assert pack.source_refs[0].chunk_id == "chunk-1"
    assert [step.step for step in pack.conversation_steps] == [
        ConversationStepName.INTENT_RECOGNITION,
        ConversationStepName.QUERY_TRANSFORMATION,
        ConversationStepName.PARALLEL_RETRIEVAL,
        ConversationStepName.CONTEXT_ASSEMBLY,
    ]
    retrieval_step = pack.conversation_steps[2]
    assert retrieval_step.status == StepStatus.COMPLETED
    assert retrieval_step.display_payload["sub_queries"][0]["item_count"] == 1
    assert len(harness.unstructured_executor.calls) == 1
    assert harness.major_distribution_executor.calls == []


def test_orchestrator_plan_preview_does_not_execute_retrieval(session):
    sub_query = _unstructured_sub_query()
    intent = _intent()
    harness = _harness(
        intent=intent,
        plan=_plan(sub_query),
        unstructured_results={"q1": _unstructured_result()},
        structured_results={},
    )

    pack = harness.orchestrator.plan("什么是直播电商？")

    assert pack.status == ContextPackStatus.PLANNED
    assert pack.retrieval_plan is not None
    assert pack.retrieval_results == []
    assert pack.source_refs == []
    assert [step.step for step in pack.conversation_steps] == [
        ConversationStepName.INTENT_RECOGNITION,
        ConversationStepName.QUERY_TRANSFORMATION,
    ]
    assert harness.unstructured_executor.calls == []
    assert harness.major_distribution_executor.calls == []


def test_orchestrator_completes_major_distribution_structured_query(session):
    sub_query = _structured_sub_query()
    intent = _intent(
        business_domains=["major_distribution"],
        retrieval_channels=["structured"],
        question_type="aggregation",
    )
    harness = _harness(
        intent=intent,
        plan=_plan(sub_query),
        unstructured_results={},
        structured_results={"q1": _structured_result()},
    )

    pack = harness.orchestrator.run(session, "近三年高职电子商务专业布点数变化")

    assert pack.status == ContextPackStatus.COMPLETED
    assert pack.retrieval_results[0].channel == "structured"
    assert pack.retrieval_results[0].aggregations[0].series == [
        {"year": 2026, "value": 16, "record_count": 2}
    ]
    assert pack.source_refs[0].record_ref == "major_distribution_record:record-1"
    assert harness.unstructured_executor.calls == []
    assert len(harness.major_distribution_executor.calls) == 1


def test_orchestrator_executes_mixed_plan_and_merges_source_refs(session):
    unstructured_sub_query = _unstructured_sub_query("q1")
    structured_sub_query = _structured_sub_query("q2")
    intent = _intent(
        business_domains=["course_textbook", "major_distribution"],
        retrieval_channels=["unstructured", "structured"],
        question_type="comparison",
    )
    harness = _harness(
        intent=intent,
        plan=_plan(unstructured_sub_query, structured_sub_query),
        unstructured_results={"q1": _unstructured_result("q1")},
        structured_results={"q2": _structured_result("q2")},
    )

    pack = harness.orchestrator.run(session, "解释概念并对比专业布点趋势")

    assert pack.status == ContextPackStatus.COMPLETED
    assert [result.query_id for result in pack.retrieval_results] == ["q1", "q2"]
    assert [ref.source_ref_id for ref in pack.source_refs] == ["q1-src-1", "q2-src-1"]
    retrieval_step = pack.conversation_steps[2]
    assert retrieval_step.progress["total"] == 2
    assert retrieval_step.progress["completed"] == 2
    assert retrieval_step.progress["failed"] == 0


def test_orchestrator_marks_partial_when_one_sub_query_fails(session):
    unstructured_sub_query = _unstructured_sub_query("q1")
    structured_sub_query = _structured_sub_query("q2")
    intent = _intent(
        business_domains=["course_textbook", "major_distribution"],
        retrieval_channels=["unstructured", "structured"],
        question_type="comparison",
    )
    harness = _harness(
        intent=intent,
        plan=_plan(unstructured_sub_query, structured_sub_query),
        unstructured_results={"q1": _unstructured_result("q1")},
        structured_results={},
        major_distribution_executor=_FailingExecutor(),
    )

    pack = harness.orchestrator.run(session, "解释概念并对比专业布点趋势")

    assert pack.status == ContextPackStatus.PARTIAL
    assert [result.status for result in pack.retrieval_results] == [
        StepStatus.COMPLETED,
        StepStatus.FAILED,
    ]
    assert pack.retrieval_results[1].error_message == (
        "RuntimeError: backend unavailable"
    )
    assert pack.source_refs[0].source_ref_id == "q1-src-1"
    assert pack.warnings == ["sub_query_failed:q2"]
    retrieval_step = pack.conversation_steps[2]
    assert retrieval_step.status == StepStatus.FAILED
    assert retrieval_step.progress["completed"] == 1
    assert retrieval_step.progress["failed"] == 1


def test_orchestrator_dispatches_job_demand_structured_query(session):
    sub_query = _domain_structured_sub_query(
        query_id="q1",
        domain=BusinessDomain.JOB_DEMAND,
        table_profile="job_demand.v1",
        query_profile="job_demand.record_list",
    )
    intent = _intent(
        business_domains=["job_demand"],
        retrieval_channels=["structured"],
        question_type="record_list",
    )
    harness = _harness(
        intent=intent,
        plan=_plan(sub_query),
        unstructured_results={},
        structured_results={"q1": _domain_structured_result("q1", BusinessDomain.JOB_DEMAND)},
    )

    pack = harness.orchestrator.run(session, "岗位需求")

    assert pack.status == ContextPackStatus.COMPLETED
    assert pack.retrieval_results[0].domain == "job_demand"
    assert len(harness.job_demand_executor.calls) == 1
    assert harness.major_distribution_executor.calls == []


def test_orchestrator_dispatches_competency_structured_query(session):
    sub_query = _domain_structured_sub_query(
        query_id="q1",
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        table_profile="ability_analysis.pgsd.v1",
        query_profile="competency.task_tree",
    )
    intent = _intent(
        business_domains=["competency_analysis"],
        retrieval_channels=["structured"],
        question_type="task_tree",
    )
    harness = _harness(
        intent=intent,
        plan=_plan(sub_query),
        unstructured_results={},
        structured_results={
            "q1": _domain_structured_result("q1", BusinessDomain.COMPETENCY_ANALYSIS)
        },
    )

    pack = harness.orchestrator.run(session, "职业能力任务树")

    assert pack.status == ContextPackStatus.COMPLETED
    assert pack.retrieval_results[0].domain == "competency_analysis"
    assert len(harness.competency_executor.calls) == 1
    assert harness.major_distribution_executor.calls == []
