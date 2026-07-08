"""Minimal v1.0 retrieval/recall orchestration loop."""
from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Protocol

from sqlalchemy.orm import Session

from nexus_app.config import Settings, get_settings
from nexus_app.retrieval.executors import (
    MajorDistributionRetrievalExecutor,
    UnstructuredRetrievalExecutor,
    create_major_distribution_retrieval_executor,
    create_unstructured_retrieval_executor,
)
from nexus_app.retrieval.intent import (
    IntentRecognitionService,
    create_intent_recognition_service,
)
from nexus_app.retrieval.planner import (
    RetrievalPlannerService,
    create_retrieval_planner_service,
)
from nexus_app.retrieval.schemas import (
    ACCESS_SCOPE_ALL_ASSETS,
    BusinessDomain,
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
)


class IntentRecognizerProtocol(Protocol):
    def recognize(self, query: str):
        ...


class RetrievalPlannerProtocol(Protocol):
    def generate_plan(self, query: str, intent: RetrievalIntent):
        ...


class RetrievalExecutorProtocol(Protocol):
    def execute(self, session: Session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        ...


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        intent_service: IntentRecognizerProtocol | None = None,
        planner_service: RetrievalPlannerProtocol | None = None,
        unstructured_executor: RetrievalExecutorProtocol | None = None,
        major_distribution_executor: RetrievalExecutorProtocol | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._intent_service = intent_service or create_intent_recognition_service(self._settings)
        self._planner_service = planner_service or create_retrieval_planner_service(self._settings)
        default_unstructured_executor = (
            unstructured_executor or create_unstructured_retrieval_executor(self._settings)
        )
        default_major_distribution_executor = (
            major_distribution_executor or create_major_distribution_retrieval_executor()
        )
        self._executors: dict[tuple[str, str], RetrievalExecutorProtocol] = {
            (
                str(RetrievalChannel.UNSTRUCTURED),
                str(BusinessDomain.COURSE_TEXTBOOK),
            ): default_unstructured_executor,
            (
                str(RetrievalChannel.UNSTRUCTURED),
                str(BusinessDomain.MAJOR_PROFILE),
            ): default_unstructured_executor,
            (
                str(RetrievalChannel.STRUCTURED),
                str(BusinessDomain.MAJOR_DISTRIBUTION),
            ): default_major_distribution_executor,
        }

    def run(self, session: Session, query: str) -> RetrievalContextPack:
        intent_result = self._intent_service.recognize(query)
        if intent_result.context_pack is not None:
            return intent_result.context_pack
        if intent_result.intent is None:
            raise RuntimeError("intent recognizer returned neither intent nor context_pack")

        steps = [intent_result.conversation_step]
        planner_result = self._planner_service.generate_plan(query, intent_result.intent)
        steps.append(planner_result.conversation_step)
        warnings = list(intent_result.warnings) + list(planner_result.warnings)

        if not planner_result.success or planner_result.plan is None:
            return RetrievalContextPack(
                status=ContextPackStatus.FAILED,
                original_query=query,
                intent=intent_result.intent,
                retrieval_plan=None,
                retrieval_results=[],
                source_refs=[],
                conversation_steps=steps,
                access_scope=ACCESS_SCOPE_ALL_ASSETS,
                warnings=warnings,
            )

        retrieval_step, results = self._execute_plan(session, planner_result.plan)
        steps.append(retrieval_step)
        source_refs = _merge_source_refs(results)
        steps.append(_context_assembly_step(results=results, source_refs=source_refs))
        status = _pack_status(results)

        return RetrievalContextPack(
            status=status,
            original_query=query,
            intent=intent_result.intent,
            retrieval_plan=planner_result.plan,
            retrieval_results=results,
            source_refs=source_refs,
            conversation_steps=steps,
            access_scope=ACCESS_SCOPE_ALL_ASSETS,
            warnings=warnings + _result_warnings(results),
        )

    def plan(self, query: str) -> RetrievalContextPack:
        intent_result = self._intent_service.recognize(query)
        if intent_result.context_pack is not None:
            return intent_result.context_pack
        if intent_result.intent is None:
            raise RuntimeError("intent recognizer returned neither intent nor context_pack")

        steps = [intent_result.conversation_step]
        planner_result = self._planner_service.generate_plan(query, intent_result.intent)
        steps.append(planner_result.conversation_step)
        warnings = list(intent_result.warnings) + list(planner_result.warnings)

        if not planner_result.success or planner_result.plan is None:
            return RetrievalContextPack(
                status=ContextPackStatus.FAILED,
                original_query=query,
                intent=intent_result.intent,
                retrieval_plan=None,
                retrieval_results=[],
                source_refs=[],
                conversation_steps=steps,
                access_scope=ACCESS_SCOPE_ALL_ASSETS,
                warnings=warnings,
            )

        return RetrievalContextPack(
            status=ContextPackStatus.PLANNED,
            original_query=query,
            intent=intent_result.intent,
            retrieval_plan=planner_result.plan,
            retrieval_results=[],
            source_refs=[],
            conversation_steps=steps,
            access_scope=ACCESS_SCOPE_ALL_ASSETS,
            warnings=warnings,
        )

    def _execute_plan(
        self,
        session: Session,
        plan: RetrievalPlan,
    ) -> tuple[ConversationStep, list[RetrievalResult]]:
        started_at = _now()
        started_monotonic = time.monotonic()
        results = [self._execute_sub_query(session, sub_query) for sub_query in plan.sub_queries]
        elapsed_ms = (time.monotonic() - started_monotonic) * 1000
        failed = [result for result in results if result.status == StepStatus.FAILED]
        completed = [result for result in results if result.status == StepStatus.COMPLETED]
        step_status = StepStatus.COMPLETED
        message = "并行检索完成"
        if failed and completed:
            step_status = StepStatus.FAILED
            message = "部分子查询执行失败，已保留可用检索结果。"
        elif failed:
            step_status = StepStatus.FAILED
            message = "所有子查询执行失败。"
        return (
            ConversationStep(
                step=ConversationStepName.PARALLEL_RETRIEVAL,
                status=step_status,
                title="并行检索",
                message=message,
                started_at=started_at,
                finished_at=_now(),
                progress={
                    "total": len(plan.sub_queries),
                    "completed": len(completed),
                    "failed": len(failed),
                    "elapsed_ms": elapsed_ms,
                },
                display_payload={
                    "sub_queries": [
                        {
                            "query_id": result.query_id,
                            "channel": result.channel,
                            "domain": result.domain,
                            "status": result.status,
                            "result_shape": result.result_shape,
                            "item_count": len(result.items),
                            "record_count": len(result.records),
                            "aggregation_count": len(result.aggregations),
                            "source_ref_count": len(result.source_refs),
                            "error_message": result.error_message,
                        }
                        for result in results
                    ]
                },
            ),
            results,
        )

    def _execute_sub_query(
        self,
        session: Session,
        sub_query: RetrievalSubQuery,
    ) -> RetrievalResult:
        executor = self._resolve_executor(sub_query)
        if executor is None:
            return _failed_result(
                sub_query,
                f"unsupported_retrieval_sub_query:{sub_query.channel}:{sub_query.domain}",
            )
        try:
            return executor.execute(session, sub_query)
        except Exception as exc:  # noqa: BLE001 - fail closed per sub query
            return _failed_result(sub_query, f"{type(exc).__name__}: {exc}")

    def _resolve_executor(
        self,
        sub_query: RetrievalSubQuery,
    ) -> RetrievalExecutorProtocol | None:
        return self._executors.get((str(sub_query.channel), str(sub_query.domain)))


def create_retrieval_orchestrator(
    settings: Settings | None = None,
    *,
    intent_service: IntentRecognitionService | None = None,
    planner_service: RetrievalPlannerService | None = None,
    unstructured_executor: UnstructuredRetrievalExecutor | None = None,
    major_distribution_executor: MajorDistributionRetrievalExecutor | None = None,
) -> RetrievalOrchestrator:
    return RetrievalOrchestrator(
        settings=settings,
        intent_service=intent_service,
        planner_service=planner_service,
        unstructured_executor=unstructured_executor,
        major_distribution_executor=major_distribution_executor,
    )


def _failed_result(sub_query: RetrievalSubQuery, message: str) -> RetrievalResult:
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=sub_query.channel,
        domain=sub_query.domain,
        status=StepStatus.FAILED,
        result_shape="error",
        error_message=message,
    )


def _merge_source_refs(results: list[RetrievalResult]) -> list[RetrievalSourceRef]:
    refs: list[RetrievalSourceRef] = []
    seen: set[str] = set()
    for result in results:
        for ref in result.source_refs:
            if ref.source_ref_id in seen:
                continue
            seen.add(ref.source_ref_id)
            refs.append(ref)
    return refs


def _pack_status(results: list[RetrievalResult]) -> ContextPackStatus:
    if not results:
        return ContextPackStatus.FAILED
    completed = sum(1 for result in results if result.status == StepStatus.COMPLETED)
    if completed == len(results):
        return ContextPackStatus.COMPLETED
    if completed > 0:
        return ContextPackStatus.PARTIAL
    return ContextPackStatus.FAILED


def _result_warnings(results: list[RetrievalResult]) -> list[str]:
    return [
        f"sub_query_failed:{result.query_id}"
        for result in results
        if result.status == StepStatus.FAILED
    ]


def _context_assembly_step(
    *,
    results: list[RetrievalResult],
    source_refs: list[RetrievalSourceRef],
) -> ConversationStep:
    return ConversationStep(
        step=ConversationStepName.CONTEXT_ASSEMBLY,
        status=StepStatus.COMPLETED if results else StepStatus.FAILED,
        title="上下文组装",
        message="检索上下文已组装为 context_pack。",
        started_at=_now(),
        finished_at=_now(),
        progress={
            "result_count": len(results),
            "source_ref_count": len(source_refs),
        },
        display_payload={
            "result_count": len(results),
            "source_ref_count": len(source_refs),
            "source_refs": [
                {
                    "source_ref_id": ref.source_ref_id,
                    "channel": ref.channel,
                    "domain": ref.domain,
                    "asset_id": ref.asset_id,
                    "asset_version_id": ref.asset_version_id,
                    "normalized_ref_id": ref.normalized_ref_id,
                    "chunk_id": ref.chunk_id,
                    "record_ref": ref.record_ref,
                    "locator": ref.locator,
                }
                for ref in source_refs
            ],
        },
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
