"""Repository-style helpers for Evidence-grounded KG build rows.

This module intentionally covers only Task Package A: lifecycle metadata
for graph builds plus latest-build lookup. Candidate selection, extractors,
merge, quality gates, and API serialization belong to later slices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models

GRAPH_TYPE = "evidence_grounded_kg"


class KnowledgeGraphBuildStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"
    DEPRECATED = "deprecated"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_graph_build(
    session: Session,
    *,
    normalized_ref_id: str,
    graph_profile: str,
    strategy_version: str,
    source_chunk_count: int = 0,
    candidate_count: int = 0,
    status: str = KnowledgeGraphBuildStatus.PENDING,
    quality_summary: dict[str, Any] | None = None,
) -> models.KnowledgeGraphBuild:
    """Create a graph build envelope.

    Caller owns commit. The function flushes so downstream rows can use the
    build id in the same transaction.
    """
    build = models.KnowledgeGraphBuild(
        normalized_ref_id=normalized_ref_id,
        graph_type=GRAPH_TYPE,
        graph_profile=graph_profile,
        strategy_version=strategy_version,
        status=str(status),
        source_chunk_count=source_chunk_count,
        candidate_count=candidate_count,
        quality_summary=quality_summary or {},
    )
    session.add(build)
    session.flush()
    return build


def get_existing_graph_build(
    session: Session,
    *,
    normalized_ref_id: str,
    graph_profile: str,
    strategy_version: str,
) -> models.KnowledgeGraphBuild | None:
    """Return the newest reusable build for an idempotent build key.

    Failed builds and historical zero-row terminal builds must not block a
    user-triggered rebuild. Only in-flight builds or terminal builds with
    formal graph rows are reusable.
    """
    return session.scalar(
        select(models.KnowledgeGraphBuild)
        .where(
            models.KnowledgeGraphBuild.normalized_ref_id == normalized_ref_id,
            models.KnowledgeGraphBuild.graph_type == GRAPH_TYPE,
            models.KnowledgeGraphBuild.graph_profile == graph_profile,
            models.KnowledgeGraphBuild.strategy_version == strategy_version,
            models.KnowledgeGraphBuild.status != KnowledgeGraphBuildStatus.DEPRECATED,
            (
                models.KnowledgeGraphBuild.status.in_(
                    (
                        KnowledgeGraphBuildStatus.PENDING,
                        KnowledgeGraphBuildStatus.RUNNING,
                    )
                )
            )
            | (
                models.KnowledgeGraphBuild.status.in_(
                    (
                        KnowledgeGraphBuildStatus.SUCCEEDED,
                        KnowledgeGraphBuildStatus.REVIEW_REQUIRED,
                    )
                )
                & (
                    (models.KnowledgeGraphBuild.fact_count > 0)
                    | (models.KnowledgeGraphBuild.node_count > 0)
                )
            ),
        )
        .order_by(
            models.KnowledgeGraphBuild.completed_at.desc().nullslast(),
            models.KnowledgeGraphBuild.created_at.desc(),
        )
        .limit(1)
    )


def get_latest_succeeded_build(
    session: Session,
    *,
    normalized_ref_id: str,
    graph_profile: str | None = None,
    strategy_version: str | None = None,
) -> models.KnowledgeGraphBuild | None:
    """Return the newest succeeded build with formal graph rows for a ref."""
    stmt = (
        select(models.KnowledgeGraphBuild)
        .where(
            models.KnowledgeGraphBuild.normalized_ref_id == normalized_ref_id,
            models.KnowledgeGraphBuild.graph_type == GRAPH_TYPE,
            models.KnowledgeGraphBuild.status == KnowledgeGraphBuildStatus.SUCCEEDED,
            (
                (models.KnowledgeGraphBuild.fact_count > 0)
                | (models.KnowledgeGraphBuild.node_count > 0)
            ),
        )
        .order_by(
            models.KnowledgeGraphBuild.completed_at.desc().nullslast(),
            models.KnowledgeGraphBuild.created_at.desc(),
        )
        .limit(1)
    )
    if graph_profile is not None:
        stmt = stmt.where(models.KnowledgeGraphBuild.graph_profile == graph_profile)
    if strategy_version is not None:
        stmt = stmt.where(
            models.KnowledgeGraphBuild.strategy_version == strategy_version
        )
    return session.scalar(stmt)


def mark_graph_build_running(
    session: Session,
    build: models.KnowledgeGraphBuild,
    *,
    source_chunk_count: int | None = None,
    candidate_count: int | None = None,
) -> models.KnowledgeGraphBuild:
    build.status = KnowledgeGraphBuildStatus.RUNNING
    if source_chunk_count is not None:
        build.source_chunk_count = source_chunk_count
    if candidate_count is not None:
        build.candidate_count = candidate_count
    session.flush()
    return build


def mark_graph_build_succeeded(
    session: Session,
    build: models.KnowledgeGraphBuild,
    *,
    node_count: int,
    edge_count: int,
    fact_count: int,
    source_chunk_count: int | None = None,
    candidate_count: int | None = None,
    quality_summary: dict[str, Any] | None = None,
) -> models.KnowledgeGraphBuild:
    build.status = KnowledgeGraphBuildStatus.SUCCEEDED
    build.node_count = node_count
    build.edge_count = edge_count
    build.fact_count = fact_count
    build.completed_at = utcnow()
    build.error_message = None
    if source_chunk_count is not None:
        build.source_chunk_count = source_chunk_count
    if candidate_count is not None:
        build.candidate_count = candidate_count
    if quality_summary is not None:
        build.quality_summary = quality_summary
    session.flush()
    return build


def mark_graph_build_failed(
    session: Session,
    build: models.KnowledgeGraphBuild,
    *,
    error_message: str,
    quality_summary: dict[str, Any] | None = None,
) -> models.KnowledgeGraphBuild:
    build.status = KnowledgeGraphBuildStatus.FAILED
    build.error_message = error_message
    build.completed_at = utcnow()
    if quality_summary is not None:
        build.quality_summary = quality_summary
    session.flush()
    return build
