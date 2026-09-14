"""System-status endpoints under `/internal/v1/`."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, select, text
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


def _status_counts(session: Session, model: type, status_column) -> dict[str, int]:
    rows = session.execute(
        select(status_column, func.count()).select_from(model).group_by(status_column)
    ).all()
    return {_enum_value(status): int(count) for status, count in rows}


def _six_month_window() -> tuple[datetime, list[datetime]]:
    now = datetime.now(timezone.utc)
    current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months: list[datetime] = []
    for offset in range(5, -1, -1):
        year = current.year
        month = current.month - offset
        while month <= 0:
            year -= 1
            month += 12
        months.append(current.replace(year=year, month=month))
    return now - timedelta(days=183), months


def _execution_duration_top(
    session: Session, cutoff: datetime, *, limit: int = 10
) -> list[schemas.WorkbenchJobDurationRead]:
    stage_duration = (
        func.extract(
            "epoch", models.JobStage.finished_at - models.JobStage.started_at
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql"
        else (
            func.julianday(models.JobStage.finished_at)
            - func.julianday(models.JobStage.started_at)
        )
        * 86400
    )
    rows = session.execute(
        select(
            models.Job.id,
            models.Job.job_type,
            models.Job.status,
            func.sum(stage_duration).label("duration_seconds"),
        )
        .join(models.JobStage, models.JobStage.job_id == models.Job.id)
        .where(
            models.Job.created_at >= cutoff,
            models.JobStage.started_at.is_not(None),
            models.JobStage.finished_at.is_not(None),
        )
        .group_by(models.Job.id, models.Job.job_type, models.Job.status)
        .order_by(func.sum(stage_duration).desc(), models.Job.id.asc())
        .limit(limit)
    ).all()
    return [
        schemas.WorkbenchJobDurationRead(
            job_id=row.id,
            job_type=_enum_value(row.job_type),
            status=_enum_value(row.status),
            duration_seconds=max(0, int(round(float(row.duration_seconds or 0)))),
        )
        for row in rows
    ]


def _queue_trend(
    session: Session, cutoff: datetime, months: list[datetime]
) -> list[schemas.WorkbenchQueueTrendRead]:
    first_stage = (
        select(
            models.JobStage.job_id,
            func.min(models.JobStage.started_at).label("first_started_at"),
        )
        .where(models.JobStage.started_at.is_not(None))
        .group_by(models.JobStage.job_id)
        .subquery()
    )
    postgres = session.bind is not None and session.bind.dialect.name == "postgresql"
    if postgres:
        month_key = func.to_char(models.Job.created_at, "YYYY-MM")
        wait_start = func.coalesce(
            first_stage.c.first_started_at, datetime.now(timezone.utc)
        )
        wait_seconds = case(
            (
                first_stage.c.first_started_at.is_not(None)
                | models.Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                func.extract("epoch", wait_start - models.Job.created_at),
            ),
            else_=None,
        )
    else:
        month_key = func.strftime("%Y-%m", models.Job.created_at)
        wait_start = func.coalesce(first_stage.c.first_started_at, datetime.now(timezone.utc))
        wait_seconds = case(
            (
                first_stage.c.first_started_at.is_not(None)
                | models.Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                (func.julianday(wait_start) - func.julianday(models.Job.created_at)) * 86400,
            ),
            else_=None,
        )

    rows = session.execute(
        select(
            month_key.label("month"),
            func.count(models.Job.id).label("queued_count"),
            func.avg(wait_seconds).label("average_wait_seconds"),
        )
        .select_from(models.Job)
        .outerjoin(first_stage, first_stage.c.job_id == models.Job.id)
        .where(models.Job.created_at >= cutoff)
        .group_by(month_key)
    ).all()
    values = {
        str(row.month): (int(row.queued_count or 0), int(round(float(row.average_wait_seconds or 0))))
        for row in rows
    }
    return [
        schemas.WorkbenchQueueTrendRead(
            month=month.strftime("%Y-%m"),
            queued_count=values.get(month.strftime("%Y-%m"), (0, 0))[0],
            average_wait_seconds=values.get(month.strftime("%Y-%m"), (0, 0))[1],
        )
        for month in months
    ]


def _latest_governance_rows(session: Session) -> list:
    # PostgreSQL can satisfy "latest row per normalized ref" with DISTINCT
    # ON. The previous portable window query materialized and ranked the full
    # governance history on every Workbench request (the dominant latency).
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        quality_score = func.coalesce(
            models.AIGovernanceRun.quality_summary["overall_score"].as_float(),
            models.AIGovernanceRun.quality_summary["quality_score"].as_float(),
            models.AIGovernanceRun.ai_output["overall_score"].as_float(),
        ).label("quality_score")
        latest = (
            select(
                models.AIGovernanceRun.id,
                models.AIGovernanceRun.normalized_ref_id,
                models.AIGovernanceRun.adoption_status,
                quality_score,
                models.AIGovernanceRun.created_at,
                models.AIGovernanceRun.updated_at,
            )
            .distinct(models.AIGovernanceRun.normalized_ref_id)
            .order_by(
                models.AIGovernanceRun.normalized_ref_id,
                models.AIGovernanceRun.created_at.desc(),
                models.AIGovernanceRun.updated_at.desc(),
                models.AIGovernanceRun.id.desc(),
            )
            .subquery()
        )
        return session.execute(
            select(latest).order_by(
                latest.c.created_at.desc(),
                latest.c.updated_at.desc(),
                latest.c.id.desc(),
            )
        ).all()

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
    # These independent totals used to be four round trips to PostgreSQL.
    # Keep the same semantics while aggregating them into one statement; the
    # Console requests this endpoint on every Workbench navigation.
    count_row = session.execute(
        select(
            select(func.count())
            .select_from(models.Asset)
            .where(models.Asset.status != AssetVersionStatus.DISABLED)
            .scalar_subquery()
            .label("asset_count"),
            select(func.count())
            .select_from(models.NormalizedAssetRef)
            .scalar_subquery()
            .label("normalized_ref_count"),
            select(func.count())
            .select_from(models.RawObject)
            .scalar_subquery()
            .label("raw_object_count"),
            select(func.count())
            .select_from(models.IngestBatch)
            .scalar_subquery()
            .label("ingest_batch_count"),
        )
    ).one()
    asset_count = int(count_row.asset_count or 0)
    normalized_ref_count = int(count_row.normalized_ref_count or 0)
    raw_object_count = int(count_row.raw_object_count or 0)
    ingest_batch_count = int(count_row.ingest_batch_count or 0)

    batch_counts = _status_counts(session, models.IngestBatch, models.IngestBatch.status)
    job_counts = _status_counts(session, models.Job, models.Job.status)
    job_count = sum(job_counts.values())
    succeeded_jobs = job_counts.get(JobStatus.SUCCEEDED.value, 0)
    # A retryable failure puts the same durable job row back in `queued`; the
    # row is counted from its current terminal state, never from attempt/error
    # history. A retry that eventually succeeds therefore contributes zero to
    # this metric.
    terminal_failed_statuses = (JobStatus.FAILED, JobStatus.DEAD_LETTERED)
    failed_jobs = sum(job_counts.get(status.value, 0) for status in terminal_failed_statuses)
    running_jobs = sum(
        job_counts.get(status.value, 0)
        for status in (JobStatus.RUNNING, JobStatus.QUEUED)
    )
    queued_jobs = job_counts.get(JobStatus.QUEUED.value, 0)
    completed_jobs = succeeded_jobs + failed_jobs

    current_runs = _latest_governance_rows(session)
    governed_ref_count = len(current_runs)
    auto_adopted = 0
    quality_scores: list[float] = []

    for run in current_runs:
        adoption_status = _enum_value(run.adoption_status)
        if adoption_status == AIGovernanceRunAdoptionStatus.AUTO_ADOPTED.value:
            auto_adopted += 1
        score = getattr(run, "quality_score", None)
        if score is None and hasattr(run, "quality_summary"):
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
    cutoff, months = _six_month_window()
    execution_duration_top = _execution_duration_top(session, cutoff)
    queue_trend = _queue_trend(session, cutoff, months)

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
        queued_jobs=queued_jobs,
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
        execution_duration_top=execution_duration_top,
        queue_trend=queue_trend,
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
