"""Structured retrieval executor for major_distribution.v1.

v1.3 PR-9 upgrade — two-phase execution.  Phase A resolves any
``tag_filters`` on the sub_query into a target_id set (narrowed to
``MAJOR_DISTRIBUTION_RECORD``) via :class:`TagAssetIndexResolver` and
injects it into ``TARGET_ID_IN_KEY``.  Phase B (SQL) detects the
sentinel and adds a ``WHERE MajorDistributionRecord.id IN (…)`` clause,
turning tag_filters × structured_filters into a bounded WHERE list
rather than a cartesian join.
"""
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
    TARGET_ID_IN_KEY,
    validate_structured_plan,
)
from nexus_app.retrieval.tag_filter_execution import (
    TagFilterExecutionResult,
    apply_target_id_in_to_filters,
    execute_tag_filters,
)
from nexus_app.retrieval.tag_resolver import TagAssetIndexResolver

AGGREGATION_PROFILES = {
    "major_distribution.trend_by_year": "year",
    "major_distribution.by_province": "province_name",
    "major_distribution.by_education_level": "education_level",
}


class MajorDistributionRetrievalExecutor:
    def __init__(
        self,
        *,
        resolver_factory: "callable | None" = None,
    ) -> None:
        # ``resolver_factory(session)`` → TagAssetIndexResolver.  Left
        # optional so tests can inject a stub; the default builds a
        # resolver with no embedding_client (L1/L1.5 only) — production
        # wires an EmbeddingClient through the orchestrator.
        self._resolver_factory = resolver_factory or (
            lambda session: TagAssetIndexResolver(session)
        )

    def execute(self, session: Session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        if sub_query.channel != RetrievalChannel.STRUCTURED:
            raise ValueError("MajorDistributionRetrievalExecutor only accepts structured sub queries")
        if sub_query.domain != BusinessDomain.MAJOR_DISTRIBUTION:
            raise ValueError("MajorDistributionRetrievalExecutor only accepts major_distribution")
        if sub_query.structured_plan is None:
            raise ValueError("structured sub query requires structured_plan")

        started = time.monotonic()

        # -- Phase A: resolve tag_filters + fold structured_filters ----
        prepared_plan, phase_a = _prepare_two_phase_plan(
            session=session,
            sub_query=sub_query,
            resolver_factory=self._resolver_factory,
        )
        # v1.3 §5.3 R3 — a short-circuit result when Phase A intersected
        # to empty on AND op.  Skip the SQL round-trip entirely.
        if phase_a.applied and not phase_a.target_ids:
            elapsed = (time.monotonic() - started) * 1000
            return _empty_result(
                sub_query=sub_query,
                phase_a=phase_a,
                elapsed_ms=elapsed,
            )

        guarded = validate_structured_plan(
            domain=BusinessDomain.MAJOR_DISTRIBUTION,
            plan=prepared_plan,
        )
        if guarded.query_profile.key in AGGREGATION_PROFILES:
            result = _execute_aggregation(session, sub_query, guarded)
        else:
            result = _execute_record_list(session, sub_query, guarded)
        result.elapsed_ms = (time.monotonic() - started) * 1000
        _attach_phase_a_meta(result, phase_a)
        return result


def create_major_distribution_retrieval_executor() -> MajorDistributionRetrievalExecutor:
    return MajorDistributionRetrievalExecutor()


# ---------------------------------------------------------------------------
# Two-phase helpers
# ---------------------------------------------------------------------------


def _prepare_two_phase_plan(
    *,
    session: Session,
    sub_query: RetrievalSubQuery,
    resolver_factory,
) -> tuple[Any, TagFilterExecutionResult]:
    """Fold ``structured_filters`` + Phase A output into ``structured_plan``.

    Returns the mutated plan (a shallow copy so the caller's original
    payload is not touched) and the Phase A result for observability.
    """
    from nexus_app.retrieval.domain_registry import get_query_profile

    profile = get_query_profile(
        BusinessDomain.MAJOR_DISTRIBUTION,
        sub_query.structured_plan.query_profile,
    )

    merged_filters: dict[str, Any] = dict(sub_query.structured_plan.filters)
    for field, value in sub_query.structured_filters.items():
        merged_filters.setdefault(field, value)

    resolver = resolver_factory(session)
    phase_a = execute_tag_filters(
        sub_query=sub_query,
        profile=profile,
        resolver=resolver,
    )
    apply_target_id_in_to_filters(
        filters=merged_filters,
        target_ids=phase_a.target_ids,
        key=TARGET_ID_IN_KEY,
    )
    prepared = sub_query.structured_plan.model_copy(
        update={"filters": merged_filters}
    )
    return prepared, phase_a


def _attach_phase_a_meta(
    result: RetrievalResult,
    phase_a: TagFilterExecutionResult,
) -> None:
    for warning in phase_a.warnings:
        if warning not in result.warnings:
            result.warnings.append(warning)
    if not phase_a.applied:
        return
    result.retrieval_meta["tag_filter_target_ids_count"] = (
        len(phase_a.target_ids or set())
    )
    result.retrieval_meta["tag_filter_bucket_hit_counts"] = dict(
        phase_a.bucket_hit_counts
    )
    result.retrieval_meta["tag_filter_match_layer_counts"] = dict(
        phase_a.match_layer_counts
    )
    if phase_a.dropped_optional_buckets:
        result.retrieval_meta["tag_filter_dropped_optional_buckets"] = list(
            phase_a.dropped_optional_buckets
        )


def _empty_result(
    *,
    sub_query: RetrievalSubQuery,
    phase_a: TagFilterExecutionResult,
    elapsed_ms: float,
) -> RetrievalResult:
    result = RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        status=StepStatus.COMPLETED,
        result_shape="record_list",
        elapsed_ms=elapsed_ms,
    )
    _attach_phase_a_meta(result, phase_a)
    return result


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
        # PR-9 — Phase A's resolved target_id set arrives here.  Bind it
        # to the anchor record.id column and skip the normal column
        # lookup path so ``_column()`` isn't asked for the sentinel.
        if field == TARGET_ID_IN_KEY:
            id_set = value if isinstance(value, (list, tuple, set)) else [value]
            stmt = stmt.where(models.MajorDistributionRecord.id.in_(id_set))
            continue
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

