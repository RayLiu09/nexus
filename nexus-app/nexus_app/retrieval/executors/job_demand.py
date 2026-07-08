"""Structured retrieval executor for job_demand.v1."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalResult,
    RetrievalSourceRef,
    RetrievalSubQuery,
    StepStatus,
    StructuredAggregation,
)
from nexus_app.retrieval.sql_guardrails import GuardedStructuredPlan, validate_structured_plan

AGGREGATION_PROFILES = {
    "job_demand.count_by_city": "city",
    "job_demand.count_by_education": "education_requirement",
    "job_demand.salary_distribution": "city",
}


class JobDemandRetrievalExecutor:
    def execute(self, session: Session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        if sub_query.channel != RetrievalChannel.STRUCTURED:
            raise ValueError("JobDemandRetrievalExecutor only accepts structured sub queries")
        if sub_query.domain != BusinessDomain.JOB_DEMAND:
            raise ValueError("JobDemandRetrievalExecutor only accepts job_demand")
        if sub_query.structured_plan is None:
            raise ValueError("structured sub query requires structured_plan")

        started = time.monotonic()
        guarded = validate_structured_plan(
            domain=BusinessDomain.JOB_DEMAND,
            plan=sub_query.structured_plan,
        )
        if guarded.query_profile.key == "job_demand.requirement_keyword":
            result = _execute_requirement_keywords(session, sub_query, guarded)
        elif guarded.query_profile.key in AGGREGATION_PROFILES:
            result = _execute_aggregation(session, sub_query, guarded)
        else:
            result = _execute_record_list(session, sub_query, guarded)
        result.elapsed_ms = (time.monotonic() - started) * 1000
        return result


def create_job_demand_retrieval_executor() -> JobDemandRetrievalExecutor:
    return JobDemandRetrievalExecutor()


def _execute_aggregation(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
) -> RetrievalResult:
    group_field = guarded.plan.group_by[0] if guarded.plan.group_by else AGGREGATION_PROFILES[
        guarded.query_profile.key
    ]
    group_column = _record_column(group_field)
    metric_column, metric_label = _aggregation_metric(guarded)
    stmt = _apply_record_filters(
        select(
            group_column.label("group_value"),
            metric_column.label("value"),
            func.count(models.JobDemandRecord.id).label("record_count"),
        )
        .select_from(models.JobDemandRecord)
        .join(models.JobDemandDataset, models.JobDemandRecord.dataset_id == models.JobDemandDataset.id)
        .group_by(group_column),
        guarded.plan.filters,
    )
    stmt = _apply_order_by(stmt, guarded, default_field=group_field)
    rows = session.execute(stmt.limit(guarded.limit)).mappings().all()
    series = [
        {
            group_field: row["group_value"],
            "value": _number(row["value"]),
            "record_count": int(row["record_count"] or 0),
        }
        for row in rows
    ]
    source_records = _matching_records(session, guarded, limit=guarded.limit)
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.JOB_DEMAND,
        status=StepStatus.COMPLETED,
        result_shape="aggregation",
        aggregations=[
            StructuredAggregation(
                group_by=[group_field],
                metric=metric_label,
                series=series,
            )
        ],
        source_refs=_source_refs_for_records(session, source_records, sub_query.query_id),
    )


def _execute_record_list(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
) -> RetrievalResult:
    stmt = _apply_record_filters(_record_select(), guarded.plan.filters)
    stmt = _apply_order_by(stmt, guarded, default_field="job_title")
    records = list(session.scalars(stmt.limit(guarded.limit)).all())
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.JOB_DEMAND,
        status=StepStatus.COMPLETED,
        result_shape="record_list",
        records=[_record_payload(record) for record in records],
        source_refs=_source_refs_for_records(session, records, sub_query.query_id),
    )


def _execute_requirement_keywords(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
) -> RetrievalResult:
    stmt = select(models.JobDemandRequirementItem, models.JobDemandRecord).join(
        models.JobDemandRecord,
        models.JobDemandRequirementItem.record_id == models.JobDemandRecord.id,
    ).join(
        models.JobDemandDataset,
        models.JobDemandRecord.dataset_id == models.JobDemandDataset.id,
    )
    stmt = _apply_requirement_filters(stmt, guarded.plan.filters)
    stmt = _apply_requirement_order_by(stmt, guarded)
    rows = list(session.execute(stmt.limit(guarded.limit)).all())
    items = [row[0] for row in rows]
    records = [row[1] for row in rows]
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.JOB_DEMAND,
        status=StepStatus.COMPLETED,
        result_shape="requirement_items",
        records=[
            {
                **_requirement_payload(item),
                "job_record": _record_payload(record),
            }
            for item, record in rows
        ],
        source_refs=_source_refs_for_requirement_items(
            session,
            items,
            records,
            sub_query.query_id,
        ),
    )


def _apply_record_filters(stmt: Select, filters: dict[str, Any]) -> Select:
    for field, value in filters.items():
        if field not in RECORD_COLUMNS:
            continue
        stmt = _apply_filter(stmt, _record_column(field), field, value)
    return stmt


def _apply_requirement_filters(stmt: Select, filters: dict[str, Any]) -> Select:
    for field, value in filters.items():
        if field in RECORD_COLUMNS:
            stmt = _apply_filter(stmt, _record_column(field), field, value)
        elif field in REQUIREMENT_COLUMNS:
            stmt = _apply_filter(stmt, _requirement_column(field), field, value)
    return stmt


def _apply_filter(stmt: Select, column, field: str, value: Any) -> Select:
    if field in {"job_title", "major_name", "item_name", "normalized_name"} and isinstance(value, str):
        return stmt.where(column.contains(value))
    if isinstance(value, dict):
        return _apply_operator_filter(stmt, column, value)
    if isinstance(value, list):
        return stmt.where(column.in_(value))
    return stmt.where(column == value)


def _apply_operator_filter(stmt: Select, column, value: dict[str, Any]) -> Select:
    if "between" in value:
        lower, upper = value["between"]
        stmt = stmt.where(column >= lower, column <= upper)
    if "gte" in value:
        stmt = stmt.where(column >= value["gte"])
    if "lte" in value:
        stmt = stmt.where(column <= value["lte"])
    return stmt


def _apply_order_by(
    stmt: Select,
    guarded: GuardedStructuredPlan,
    *,
    default_field: str,
    default_direction: str = "asc",
) -> Select:
    if not guarded.plan.order_by:
        column = _record_column(default_field)
        return stmt.order_by(desc(column) if default_direction == "desc" else asc(column))
    for order in guarded.plan.order_by:
        column = _record_column(order.field)
        stmt = stmt.order_by(desc(column) if order.direction == "desc" else asc(column))
    return stmt


def _apply_requirement_order_by(stmt: Select, guarded: GuardedStructuredPlan) -> Select:
    if not guarded.plan.order_by:
        return stmt.order_by(asc(models.JobDemandRequirementItem.item_name))
    for order in guarded.plan.order_by:
        if order.field in REQUIREMENT_COLUMNS:
            column = _requirement_column(order.field)
        else:
            column = _record_column(order.field)
        stmt = stmt.order_by(desc(column) if order.direction == "desc" else asc(column))
    return stmt


def _matching_records(
    session: Session,
    guarded: GuardedStructuredPlan,
    *,
    limit: int,
) -> list[models.JobDemandRecord]:
    stmt = _apply_record_filters(_record_select(), guarded.plan.filters)
    stmt = _apply_order_by(stmt, guarded, default_field="job_title")
    return list(session.scalars(stmt.limit(limit)).all())


def _record_select() -> Select:
    return select(models.JobDemandRecord).join(
        models.JobDemandDataset,
        models.JobDemandRecord.dataset_id == models.JobDemandDataset.id,
    )


def _source_refs_for_records(
    session: Session,
    records: list[models.JobDemandRecord],
    query_id: str,
) -> list[RetrievalSourceRef]:
    refs: list[RetrievalSourceRef] = []
    dataset_cache: dict[str, models.JobDemandDataset | None] = {}
    version_cache: dict[str, models.AssetVersion | None] = {}
    for index, record in enumerate(records, start=1):
        dataset = dataset_cache.setdefault(
            record.dataset_id,
            session.get(models.JobDemandDataset, record.dataset_id),
        )
        asset_version_id = dataset.asset_version_id if dataset else None
        version = (
            version_cache.setdefault(asset_version_id, session.get(models.AssetVersion, asset_version_id))
            if asset_version_id else None
        )
        refs.append(
            RetrievalSourceRef(
                source_ref_id=f"{query_id}-src-{index}",
                channel=RetrievalChannel.STRUCTURED,
                domain=BusinessDomain.JOB_DEMAND,
                asset_id=version.asset_id if version else None,
                asset_version_id=asset_version_id,
                normalized_ref_id=record.normalized_ref_id,
                record_ref=f"job_demand_record:{record.id}",
                locator=_locator_from_trace(record.trace),
                metadata={
                    "dataset_id": record.dataset_id,
                    "record_id": record.id,
                    "source_record_key": record.source_record_key,
                    "query_id": query_id,
                },
            )
        )
    return refs


def _source_refs_for_requirement_items(
    session: Session,
    items: list[models.JobDemandRequirementItem],
    records: list[models.JobDemandRecord],
    query_id: str,
) -> list[RetrievalSourceRef]:
    refs = _source_refs_for_records(session, records, query_id)
    for ref, item in zip(refs, items, strict=False):
        ref.record_ref = f"job_demand_requirement_item:{item.id}"
        ref.metadata["requirement_item_id"] = item.id
        ref.metadata["item_type"] = item.item_type
    return refs


def _record_payload(record: models.JobDemandRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "job_title": record.job_title,
        "employment_type": record.employment_type,
        "job_count": record.job_count,
        "city": record.city,
        "region": record.region,
        "salary_min": record.salary_min,
        "salary_max": record.salary_max,
        "salary_text": record.salary_text,
        "education_requirement": record.education_requirement,
        "company_name": record.company_name,
        "enterprise_size": record.enterprise_size,
        "industry_name": record.industry_name,
        "job_skill_text": record.job_skill_text,
        "requirement_text": record.requirement_text,
    }


def _requirement_payload(item: models.JobDemandRequirementItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "record_id": item.record_id,
        "dataset_id": item.dataset_id,
        "item_type": item.item_type,
        "item_name": item.item_name,
        "raw_text": item.raw_text,
        "normalized_name": item.normalized_name,
        "taxonomy_code": item.taxonomy_code,
        "confidence": item.confidence,
        "evidence_field": item.evidence_field,
    }


def _aggregation_metric(guarded: GuardedStructuredPlan):
    if guarded.plan.metrics:
        metric = guarded.plan.metrics[0]
        label = f"{metric.function}({metric.field})"
        if metric.function == "sum" and metric.field == "job_count":
            return func.sum(models.JobDemandRecord.job_count), label
        if metric.function == "avg" and metric.field == "salary_min":
            return func.avg(models.JobDemandRecord.salary_min), label
        if metric.function == "avg" and metric.field == "salary_max":
            return func.avg(models.JobDemandRecord.salary_max), label
    return func.count(models.JobDemandRecord.id), "count(record)"


def _number(value: Any) -> int | float:
    if value is None:
        return 0
    if isinstance(value, float):
        return round(value, 2)
    return int(value)


def _locator_from_trace(trace: dict[str, Any]) -> dict[str, Any]:
    locator = dict(trace or {})
    row = locator.get("row")
    if isinstance(row, int):
        locator["row_range"] = [row, row]
    return locator


RECORD_COLUMNS = {
    "major_name": models.JobDemandDataset.major_name,
    "industry_name": models.JobDemandRecord.industry_name,
    "job_title": models.JobDemandRecord.job_title,
    "city": models.JobDemandRecord.city,
    "region": models.JobDemandRecord.region,
    "education_requirement": models.JobDemandRecord.education_requirement,
    "employment_type": models.JobDemandRecord.employment_type,
    "enterprise_size": models.JobDemandRecord.enterprise_size,
    "company_name": models.JobDemandRecord.company_name,
    "salary_min": models.JobDemandRecord.salary_min,
    "salary_max": models.JobDemandRecord.salary_max,
    "job_count": models.JobDemandRecord.job_count,
    "source_platform": models.JobDemandRecord.source_platform,
}


REQUIREMENT_COLUMNS = {
    "item_type": models.JobDemandRequirementItem.item_type,
    "item_name": models.JobDemandRequirementItem.item_name,
    "normalized_name": models.JobDemandRequirementItem.normalized_name,
    "taxonomy_code": models.JobDemandRequirementItem.taxonomy_code,
    "evidence_field": models.JobDemandRequirementItem.evidence_field,
}


def _record_column(field: str):
    try:
        return RECORD_COLUMNS[field]
    except KeyError as exc:
        raise ValueError(f"unsupported job_demand field {field!r}") from exc


def _requirement_column(field: str):
    try:
        return REQUIREMENT_COLUMNS[field]
    except KeyError as exc:
        raise ValueError(f"unsupported job_demand requirement field {field!r}") from exc
