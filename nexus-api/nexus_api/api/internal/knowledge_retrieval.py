"""Internal v1.0 knowledge retrieval/recall API for Console."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import response
from nexus_app.database import get_db
from nexus_app.retrieval import (
    ContextPackStatus,
    RetrievalContextPack,
    RetrievalOrchestrator,
    RetrievalSummaryService,
    create_retrieval_orchestrator,
    create_retrieval_summary_service,
)

router = APIRouter()


class KnowledgeRetrievalOptions(BaseModel):
    enable_llm_summary: bool = True


class KnowledgeRetrievalQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    options: KnowledgeRetrievalOptions = Field(default_factory=KnowledgeRetrievalOptions)


class KnowledgeRetrievalPlanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def get_retrieval_orchestrator() -> RetrievalOrchestrator:
    return create_retrieval_orchestrator()


def get_retrieval_summary_service() -> RetrievalSummaryService:
    return create_retrieval_summary_service()


@router.post(
    "/knowledge-retrieval/query",
    response_model=schemas.ApiResponse[dict],
)
def run_knowledge_retrieval_query(
    payload: KnowledgeRetrievalQueryRequest,
    request: Request,
    session: Session = Depends(get_db),
    orchestrator: RetrievalOrchestrator = Depends(get_retrieval_orchestrator),
    summary_service: RetrievalSummaryService = Depends(get_retrieval_summary_service),
):
    context_pack = orchestrator.run(session, payload.query)
    if _should_generate_summary(context_pack, payload.options):
        summary_result = summary_service.generate(context_pack)
        context_pack = context_pack.model_copy(
            update={
                "llm_summary": summary_result.summary,
                "warnings": _dedupe(
                    [*context_pack.warnings, *summary_result.warnings]
                ),
            }
        )
        _append_summary_step(context_pack, summary_result.warnings)
    elif context_pack.status == ContextPackStatus.NEEDS_CLARIFICATION:
        _append_summary_skipped_step(
            context_pack,
            "意图置信度不足，等待用户优化问题后再生成 Markdown 结果。",
        )
    elif not payload.options.enable_llm_summary:
        _append_summary_skipped_step(context_pack, "请求关闭了 Markdown 汇总生成。")
    else:
        _append_summary_skipped_step(context_pack, "没有可用于 Markdown 汇总的检索证据。")

    return response(_context_pack_payload(context_pack), request)


@router.post(
    "/knowledge-retrieval/plans",
    response_model=schemas.ApiResponse[dict],
)
def preview_knowledge_retrieval_plan(
    payload: KnowledgeRetrievalPlanRequest,
    request: Request,
    session: Session = Depends(get_db),
    orchestrator: RetrievalOrchestrator = Depends(get_retrieval_orchestrator),
):
    context_pack = orchestrator.plan(payload.query)
    return response(_context_pack_payload(context_pack, include_results=False), request)


def _should_generate_summary(
    context_pack: RetrievalContextPack,
    options: KnowledgeRetrievalOptions,
) -> bool:
    if not options.enable_llm_summary:
        return False
    if context_pack.status == ContextPackStatus.NEEDS_CLARIFICATION:
        return False
    return bool(context_pack.source_refs)


def _append_summary_step(
    context_pack: RetrievalContextPack,
    warnings: tuple[str, ...],
) -> None:
    from nexus_app.retrieval import ConversationStep, ConversationStepName, StepStatus

    context_pack.conversation_steps.append(
        ConversationStep(
            step=ConversationStepName.SUMMARY_GENERATION,
            status=StepStatus.COMPLETED,
            title="结果汇总",
            message="Markdown 检索/召回结果已生成。",
            display_payload={
                "format": context_pack.llm_summary.format if context_pack.llm_summary else None,
                "source_ref_ids": (
                    context_pack.llm_summary.source_ref_ids
                    if context_pack.llm_summary else []
                ),
                "warnings": list(warnings),
            },
        )
    )


def _append_summary_skipped_step(
    context_pack: RetrievalContextPack,
    message: str,
) -> None:
    from nexus_app.retrieval import ConversationStep, ConversationStepName, StepStatus

    context_pack.conversation_steps.append(
        ConversationStep(
            step=ConversationStepName.SUMMARY_GENERATION,
            status=StepStatus.SKIPPED,
            title="结果汇总",
            message=message,
        )
    )


def _context_pack_payload(
    context_pack: RetrievalContextPack,
    *,
    include_results: bool = True,
) -> dict[str, Any]:
    payload = context_pack.model_dump(mode="json")
    payload["markdown"] = (
        context_pack.llm_summary.content
        if include_results and context_pack.llm_summary is not None
        else None
    )
    if not include_results:
        payload["retrieval_results"] = []
        payload["source_refs"] = []
        payload["llm_summary"] = None
        payload["markdown"] = None
    return payload


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
