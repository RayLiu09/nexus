"""Structured retrieval executor for major_distribution.v1."""
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
from nexus_app.retrieval.sql_guardrails import (
    GuardedStructuredPlan,
    validate_structured_plan,
)

AGGREGATION_PROFILES = {
    "major_distribution.trend_by_year": "year",
    "major_distribution.by_province": "province_name",
    "major_distribution.by_education_level": "education_level",
}


class MajorDistributionRetrievalExecutor:
    def execute(self, session: Session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        if sub_query.channel != RetrievalChannel.STRUCTURED:
            raise ValueError("MajorDistributionRetrievalExecutor only accepts structured sub queries")
        if sub_query.domain != BusinessDomain.MAJOR_DISTRIBUTION:
            raise ValueError("MajorDistributionRetrievalExecutor only accepts major_distribution")
        if sub_query.structured_plan is None:
            raise ValueError("structured sub query requires structured_plan")

        started = time.monotonic()
        guarded = validate_structured_plan(
            domain=BusinessDomain.MAJOR_DISTRIBUTION,
            plan=sub_query.structured_plan,
        )
        if guarded.query_profile.key in AGGREGATION_PROFILES:
            result = _execute_aggregation(session, sub_query, guarded)
        else:
            result = _execute_record_list(session, sub_query, guarded)
        result.elapsed_ms = (time.monotonic() - started) * 1000
        return result


def create_major_distribution_retrieval_executor() -> MajorDistributionRetrievalExecutor:
    return MajorDistributionRetrievalExecutor()


def _execute_aggregation(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
) -> RetrievalResult:
    group_field = (
        guarded.plan.group_by[0]
        if guarded.plan.group_by
        else AGGREGATION_PROFILES[guarded.query_profile.key]
    )
    group_column = _column(group_field)
    stmt = _apply_filters(
        select(
            group_column.label("group_value"),
            func.sum(models.MajorDistributionRecord.distribution_count).label("value"),
            func.count(models.MajorDistributionRecord.id).label("record_count"),
        ).group_by(group_column),
        guarded.plan.filters,
    )
    stmt = _apply_order_by(stmt, guarded, default_field=group_field)
    rows = session.execute(stmt.limit(guarded.limit)).mappings().all()
    series = [
        {
            group_field: row["group_value"],
            "value": int(row["value"] or 0),
            "record_count": int(row["record_count"] or 0),
        }
        for row in rows
    ]
    source_records = _matching_records(session, guarded, limit=guarded.limit)
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        status=StepStatus.COMPLETED,
        result_shape="aggregation",
        aggregations=[
            StructuredAggregation(
                group_by=[group_field],
                metric=_metric_label(guarded),
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
    stmt = _apply_filters(select(models.MajorDistributionRecord), guarded.plan.filters)
    stmt = _apply_order_by(
        stmt,
        guarded,
        default_field="year",
        default_direction="desc",
    )
    records = list(session.scalars(stmt.limit(guarded.limit)).all())
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        status=StepStatus.COMPLETED,
        result_shape="record_list",
        records=[_record_payload(record) for record in records],
        source_refs=_source_refs_for_records(session, records, sub_query.query_id),
    )


def _apply_filters(stmt: Select, filters: dict[str, Any]) -> Select:
    for field, value in filters.items():
        column = _column(field)
        if field == "major_name" and isinstance(value, str):
            stmt = stmt.where(column.contains(value))
        elif isinstance(value, dict):
            stmt = _apply_operator_filter(stmt, column, value)
        elif isinstance(value, list):
            stmt = stmt.where(column.in_(value))
        else:
            stmt = stmt.where(column == value)
    return stmt


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
    order_by = guarded.plan.order_by
    if not order_by:
        column = _column(default_field)
        return stmt.order_by(desc(column) if default_direction == "desc" else asc(column))
    for order in order_by:
        column = _column(order.field)
        stmt = stmt.order_by(desc(column) if order.direction == "desc" else asc(column))
    return stmt


def _matching_records(
    session: Session,
    guarded: GuardedStructuredPlan,
    *,
    limit: int,
) -> list[models.MajorDistributionRecord]:
    stmt = _apply_filters(select(models.MajorDistributionRecord), guarded.plan.filters)
    stmt = _apply_order_by(stmt, guarded, default_field="year")
    return list(session.scalars(stmt.limit(limit)).all())


def _source_refs_for_records(
    session: Session,
    records: list[models.MajorDistributionRecord],
    query_id: str,
) -> list[RetrievalSourceRef]:
    refs: list[RetrievalSourceRef] = []
    dataset_cache: dict[str, models.MajorDistributionDataset | None] = {}
    version_cache: dict[str, models.AssetVersion | None] = {}
    for index, record in enumerate(records, start=1):
        dataset = dataset_cache.setdefault(
            record.dataset_id,
            session.get(models.MajorDistributionDataset, record.dataset_id),
        )
        version = None
        asset_id = None
        asset_version_id = dataset.asset_version_id if dataset else None
        if asset_version_id:
            version = version_cache.setdefault(
                asset_version_id,
                session.get(models.AssetVersion, asset_version_id),
            )
            asset_id = version.asset_id if version else None
        refs.append(
            RetrievalSourceRef(
                source_ref_id=f"{query_id}-src-{index}",
                channel=RetrievalChannel.STRUCTURED,
                domain=BusinessDomain.MAJOR_DISTRIBUTION,
                asset_id=asset_id,
                asset_version_id=asset_version_id,
                normalized_ref_id=record.normalized_ref_id,
                record_ref=f"major_distribution_record:{record.id}",
                locator={
                    "source_row_no": record.source_row_no,
                    "row_range": _row_range(record.source_row_no),
                },
                metadata={
                    "dataset_id": record.dataset_id,
                    "record_id": record.id,
                    "source_record_key": record.source_record_key,
                    "query_id": query_id,
                },
            )
        )
    return refs


def _record_payload(record: models.MajorDistributionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_row_no": record.source_row_no,
        "year": record.year,
        "province_name": record.province_name,
        "region_scope": record.region_scope,
        "major_name": record.major_name,
        "major_code": record.major_code,
        "education_level": record.education_level,
        "distribution_count": record.distribution_count,
    }


def _metric_label(guarded: GuardedStructuredPlan) -> str:
    if guarded.plan.metrics:
        metric = guarded.plan.metrics[0]
        return f"{metric.function}({metric.field})"
    return "sum(distribution_count)"


def _column(field: str):
    columns = {
        "year": models.MajorDistributionRecord.year,
        "province_name": models.MajorDistributionRecord.province_name,
        "major_code": models.MajorDistributionRecord.major_code,
        "major_name": models.MajorDistributionRecord.major_name,
        "education_level": models.MajorDistributionRecord.education_level,
        "region_scope": models.MajorDistributionRecord.region_scope,
        "distribution_count": models.MajorDistributionRecord.distribution_count,
    }
    try:
        return columns[field]
    except KeyError as exc:
        raise ValueError(f"unsupported major_distribution field {field!r}") from exc


def _row_range(source_row_no: str | None) -> list[int] | None:
    if not source_row_no:
        return None
    try:
        row = int(source_row_no)
    except ValueError:
        return None
    return [row, row]

