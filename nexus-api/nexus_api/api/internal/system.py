"""System-status endpoints under `/internal/v1/`."""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal.governance_review_queue import pending_review_result_ids
from nexus_api.responses import response
from nexus_app import models
from nexus_app import schemas as domain_schemas
from nexus_app.database import get_db
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AssetVersionStatus,
    IngestBatchStatus,
    JobStatus,
)

router = APIRouter()


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _rounded_percentage(numerator: int, denominator: int, *, empty: int = 0) -> int:
    if denominator <= 0:
        return empty
    return math.floor((numerator / denominator) * 100 + 0.5)


def _quality_score(
    quality_summary: dict | None,
    ai_output: dict | None,
) -> float | None:
    candidates = (
        (quality_summary or {}).get("overall_score"),
        (quality_summary or {}).get("quality_score"),
        (ai_output or {}).get("overall_score"),
    )
    for value in candidates:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _count_rows(session: Session, model: type, *criteria: object) -> int:
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(session.scalar(statement) or 0)


def _status_counts(session: Session, model: type, status_column) -> dict[str, int]:
    rows = session.execute(
        select(status_column, func.count()).select_from(model).group_by(status_column)
    ).all()
    return {_enum_value(status): int(count) for status, count in rows}


def _latest_governance_rows(session: Session) -> list:
    ranked = (
        select(
            models.AIGovernanceRun.id.label("id"),
            models.AIGovernanceRun.normalized_ref_id.label("normalized_ref_id"),
            models.AIGovernanceRun.adoption_status.label("adoption_status"),
            models.AIGovernanceRun.quality_summary.label("quality_summary"),
            models.AIGovernanceRun.ai_output.label("ai_output"),
            models.AIGovernanceRun.created_at.label("created_at"),
            models.AIGovernanceRun.updated_at.label("updated_at"),
            func.row_number()
            .over(
                partition_by=models.AIGovernanceRun.normalized_ref_id,
                order_by=(
                    models.AIGovernanceRun.created_at.desc(),
                    models.AIGovernanceRun.updated_at.desc(),
                    models.AIGovernanceRun.id.desc(),
                ),
            )
            .label("row_number"),
        )
        .subquery()
    )
    return session.execute(
        select(
            ranked.c.id,
            ranked.c.normalized_ref_id,
            ranked.c.adoption_status,
            ranked.c.quality_summary,
            ranked.c.ai_output,
            ranked.c.created_at,
            ranked.c.updated_at,
        )
        .where(ranked.c.row_number == 1)
        .order_by(
            ranked.c.created_at.desc(),
            ranked.c.updated_at.desc(),
            ranked.c.id.desc(),
        )
    ).all()


def build_workbench_summary(session: Session) -> schemas.WorkbenchSummaryRead:
    asset_count = _count_rows(
        session,
        models.Asset,
        models.Asset.status != AssetVersionStatus.DISABLED,
    )
    normalized_ref_count = _count_rows(session, models.NormalizedAssetRef)
    raw_object_count = _count_rows(session, models.RawObject)
    ingest_batch_count = _count_rows(session, models.IngestBatch)

    batch_counts = _status_counts(session, models.IngestBatch, models.IngestBatch.status)
    job_counts = _status_counts(session, models.Job, models.Job.status)
    job_count = sum(job_counts.values())
    succeeded_jobs = job_counts.get(JobStatus.SUCCEEDED.value, 0)
    failed_jobs = sum(
        job_counts.get(status.value, 0)
        for status in (JobStatus.FAILED, JobStatus.DEAD_LETTERED)
    )
    running_jobs = sum(
        job_counts.get(status.value, 0)
        for status in (JobStatus.RUNNING, JobStatus.QUEUED)
    )
    completed_jobs = succeeded_jobs + failed_jobs

    current_runs = _latest_governance_rows(session)
    governed_ref_count = len(current_runs)
    auto_adopted = 0
    quality_scores: list[float] = []

    for run in current_runs:
        adoption_status = _enum_value(run.adoption_status)
        if adoption_status == AIGovernanceRunAdoptionStatus.AUTO_ADOPTED.value:
            auto_adopted += 1
        score = _quality_score(run.quality_summary, run.ai_output)
        if score is not None:
            quality_scores.append(score)

    review_result_ids, review_required = pending_review_result_ids(
        session,
        limit=5,
        offset=0,
    )
    review_items = [
        schemas.WorkbenchReviewItemRead(
            id=result.id,
            normalized_ref_id=result.normalized_ref_id,
            adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED.value,
        )
        for result in session.scalars(
            select(models.GovernanceResult).where(
                models.GovernanceResult.id.in_(review_result_ids)
            )
        ).all()
    ]
    review_items_by_id = {item.id: item for item in review_items}
    review_items = [
        review_items_by_id[result_id]
        for result_id in review_result_ids
        if result_id in review_items_by_id
    ]

    quality_pass = sum(score >= 80 for score in quality_scores)
    quality_warning = sum(60 <= score < 80 for score in quality_scores)
    quality_fail = sum(score < 60 for score in quality_scores)
    avg_quality = (
        math.floor(sum(quality_scores) / len(quality_scores) + 0.5)
        if quality_scores
        else 0
    )

    return schemas.WorkbenchSummaryRead(
        asset_count=asset_count,
        normalized_ref_count=normalized_ref_count,
        raw_object_count=raw_object_count,
        ingest_batch_count=ingest_batch_count,
        processing_batches=batch_counts.get(IngestBatchStatus.PROCESSING.value, 0),
        job_count=job_count,
        succeeded_jobs=succeeded_jobs,
        failed_jobs=failed_jobs,
        running_jobs=running_jobs,
        pipeline_health=_rounded_percentage(
            succeeded_jobs,
            completed_jobs,
            empty=100,
        ),
        governed_ref_count=governed_ref_count,
        governance_coverage=_rounded_percentage(
            governed_ref_count,
            normalized_ref_count,
        ),
        auto_adopted=auto_adopted,
        review_required=review_required,
        quality_pass=quality_pass,
        quality_warning=quality_warning,
        quality_fail=quality_fail,
        avg_quality=avg_quality,
        review_items=review_items,
    )


@router.get(
    "/runtime/state",
    response_model=schemas.ApiResponse[domain_schemas.RuntimeStateRead],
)
def runtime_state(request: Request, session: Session = Depends(get_db)):
    database = "ok"
    try:
        session.execute(text("select 1"))
    except Exception:
        database = "error"
    app = getattr(request, "app", None)
    app_state = getattr(app, "state", None)
    workers = "not_configured" if app_state is None else "unknown"
    pool = getattr(app_state, "worker_pool", None)
    if pool is not None:
        state = pool.state()
        workers = (
            f"running {state.running_threads}/{state.configured_size}"
            if state.enabled
            else "disabled"
        )

    queue = "not_configured" if app_state is None else "unknown"
    try:
        queued = session.scalar(
            text("select count(*) from job where status = 'queued'")
        )
        queue = f"queued={queued or 0}"
    except Exception:
        queue = "error"

    return response(
        domain_schemas.RuntimeStateRead(
            api="ok",
            database=database,
            workers=workers,
            queue=queue,
            recent_error=None,
        ),
        request,
    )


@router.get(
    "/workbench/summary",
    response_model=schemas.ApiResponse[schemas.WorkbenchSummaryRead],
)
def workbench_summary(request: Request, session: Session = Depends(get_db)):
    return response(build_workbench_summary(session), request)
