"""Background processor for pending Evidence-grounded KG builds."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import LiteLLMClientProtocol
from nexus_app.config import Settings, get_settings
from nexus_app.evidence_graph.extractors import extract_graph_candidates
from nexus_app.evidence_graph.persist import GraphPersistResult, persist_graph_candidates
from nexus_app.evidence_graph.service import (
    GRAPH_TYPE,
    KnowledgeGraphBuildStatus,
    mark_graph_build_failed,
    mark_graph_build_running,
)

logger = logging.getLogger(__name__)

DEFAULT_RUNNING_STALE_SECONDS = 6 * 3600


@dataclass(frozen=True)
class GraphBuildProcessResult:
    build_id: str
    status: str
    selected_chunk_count: int
    extracted_candidate_count: int
    persisted: GraphPersistResult | None
    quality_summary: dict[str, Any]


def claim_pending_graph_build(
    session: Session,
    *,
    worker_id: str,
) -> models.KnowledgeGraphBuild | None:
    """Claim the oldest pending graph build.

    Caller owns commit. PostgreSQL deployments use ``FOR UPDATE SKIP LOCKED``;
    SQLite tests ignore the lock clause.
    """
    stmt = (
        select(models.KnowledgeGraphBuild)
        .where(
            models.KnowledgeGraphBuild.graph_type == GRAPH_TYPE,
            models.KnowledgeGraphBuild.status == KnowledgeGraphBuildStatus.PENDING,
        )
        .order_by(models.KnowledgeGraphBuild.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    build = session.scalar(stmt)
    if build is None:
        return None
    summary = dict(build.quality_summary or {})
    summary["claimed_by"] = worker_id
    mark_graph_build_running(
        session,
        build,
        source_chunk_count=build.source_chunk_count,
        candidate_count=build.candidate_count,
    )
    build.quality_summary = summary
    session.flush()
    return build


def recover_stale_running_graph_builds(
    session: Session,
    *,
    stale_after_seconds: int = DEFAULT_RUNNING_STALE_SECONDS,
) -> int:
    """Return stale running builds to pending after worker interruption.

    Evidence Graph builds are not backed by the generic job lease table. During
    local reloads or process exits a build can remain ``running`` forever after
    being claimed. The recovery is intentionally conservative and only touches
    builds whose ``updated_at`` is older than the stale threshold.
    """
    from nexus_app.models import utcnow

    cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
    rows = list(
        session.scalars(
            select(models.KnowledgeGraphBuild)
            .where(
                models.KnowledgeGraphBuild.graph_type == GRAPH_TYPE,
                models.KnowledgeGraphBuild.status == KnowledgeGraphBuildStatus.RUNNING,
                models.KnowledgeGraphBuild.updated_at < cutoff,
            )
            .order_by(models.KnowledgeGraphBuild.updated_at.asc())
            .with_for_update(skip_locked=True)
        )
    )
    for build in rows:
        summary = dict(build.quality_summary or {})
        recoveries = list(summary.get("running_recoveries") or [])
        recoveries.append({
            "reason": "stale_running_requeued",
            "stale_after_seconds": stale_after_seconds,
            "previous_status": str(build.status),
            "previous_updated_at": build.updated_at.isoformat() if build.updated_at else None,
        })
        summary["running_recoveries"] = recoveries[-5:]
        build.status = KnowledgeGraphBuildStatus.PENDING
        build.error_message = None
        build.quality_summary = summary
    if rows:
        session.flush()
    return len(rows)


def process_graph_build(
    session: Session,
    build: models.KnowledgeGraphBuild,
    *,
    llm_client: LiteLLMClientProtocol | None = None,
) -> GraphBuildProcessResult:
    """Execute candidate selection, extraction, and evidence-bound persistence."""
    try:
        selection = _select_candidates(session, build)
        mark_graph_build_running(
            session,
            build,
            source_chunk_count=selection.total_semantic_chunk_count,
            candidate_count=selection.selected_chunk_count,
        )
        session.flush()

        results = extract_graph_candidates(
            selection.candidate_chunks,
            graph_profile=build.graph_profile,
            llm_client=llm_client,
        )
        accepted = [item for result in results for item in result.accepted]
        rejected_count = sum(result.rejected_count for result in results)
        rejected_by_reason: dict[str, int] = {}
        reject_samples: list[dict[str, Any]] = []
        for result in results:
            for reason, count in result.reject_reasons.items():
                rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + count
            for sample in result.reject_samples:
                if len(reject_samples) >= 10:
                    break
                reject_samples.append({
                    **sample,
                    "source_chunk_id": sample.get("source_chunk_id") or result.source_chunk_id,
                })
        persisted = persist_graph_candidates(
            session,
            build=build,
            candidates=accepted,
            chunk_candidates=selection.candidate_chunks,
            source_candidate_count=selection.selected_chunk_count,
            extraction_rejected_count=rejected_count,
        )
        summary = {
            **(build.quality_summary or {}),
            "candidate_selection": _selection_to_dict(selection),
            "extraction": {
                "accepted": len(accepted),
                "rejected": rejected_count,
                "rejected_by_reason": rejected_by_reason,
                "reject_samples": reject_samples,
            },
            "persist": persisted.quality_summary,
        }
        build.quality_summary = summary
        session.flush()
        return GraphBuildProcessResult(
            build_id=build.id,
            status=str(persisted.status),
            selected_chunk_count=selection.selected_chunk_count,
            extracted_candidate_count=len(accepted),
            persisted=persisted,
            quality_summary=summary,
        )
    except Exception as exc:
        logger.exception("Evidence graph build %s failed", build.id)
        summary = dict(build.quality_summary or {})
        summary["processor_error"] = type(exc).__name__
        mark_graph_build_failed(
            session,
            build,
            error_message=str(exc)[:1000],
            quality_summary=summary,
        )
        return GraphBuildProcessResult(
            build_id=build.id,
            status=str(KnowledgeGraphBuildStatus.FAILED),
            selected_chunk_count=0,
            extracted_candidate_count=0,
            persisted=None,
            quality_summary=summary,
        )


def process_one_pending_graph_build(
    session: Session,
    *,
    worker_id: str,
    llm_client: LiteLLMClientProtocol | None = None,
    settings: Settings | None = None,
) -> GraphBuildProcessResult | None:
    """Claim and process one pending Evidence Graph build."""
    recovered = recover_stale_running_graph_builds(session)
    if recovered:
        session.commit()
    build = claim_pending_graph_build(session, worker_id=worker_id)
    if build is None:
        return None
    session.commit()

    build = session.get(models.KnowledgeGraphBuild, build.id)
    if build is None:
        return None
    client = llm_client
    if client is None:
        client = _build_default_llm_client(settings or get_settings())
    result = process_graph_build(session, build, llm_client=client)
    session.commit()
    return result


def _build_default_llm_client(settings: Settings) -> LiteLLMClientProtocol | None:
    try:
        from nexus_app.ai_governance.services import _create_default_litellm_client

        return _create_default_litellm_client(settings)
    except Exception:
        logger.exception("Evidence graph LLM client unavailable")
        return None


def _select_candidates(session: Session, build: models.KnowledgeGraphBuild):
    from nexus_app.evidence_graph.candidates import select_graph_candidate_chunks

    return select_graph_candidate_chunks(
        session,
        normalized_ref_id=build.normalized_ref_id,
        graph_profile=build.graph_profile,
    )


def _selection_to_dict(selection) -> dict[str, Any]:
    return {
        "normalized_ref_id": selection.normalized_ref_id,
        "graph_profile": selection.graph_profile,
        "selected_chunk_count": selection.selected_chunk_count,
        "skipped_chunk_count": selection.skipped_chunk_count,
        "total_semantic_chunk_count": selection.total_semantic_chunk_count,
        "by_anchor_role": selection.by_anchor_role,
        "skipped_by_reason": selection.skipped_by_reason,
    }
