"""Read only Ministry school/year/major facts; no legacy dataset or AI join."""

from __future__ import annotations

import time
from typing import Any
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session
from nexus_app import models
from nexus_app.major_offerings import serialize
from nexus_app.domain_normalize.administrative_division import normalize_province_name
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
    StructuredPlanGuardrailError,
    validate_structured_plan,
    validate_tag_filters,
)

AGGREGATION_PROFILES = {
    "major_distribution.trend_by_year": "year",
    "major_distribution.by_province": "province_name",
}


class MajorDistributionRetrievalExecutor:
    def __init__(self, *, resolver_factory=None, rerank_enabled=None):
        # Kept for the executor factory interface; these facts have no AI tags.
        pass

    def execute(
        self, session: Session, sub_query: RetrievalSubQuery
    ) -> RetrievalResult:
        if (
            sub_query.channel != RetrievalChannel.STRUCTURED
            or sub_query.domain != BusinessDomain.MAJOR_DISTRIBUTION
        ):
            raise ValueError(
                "major offerings require a structured major_distribution query"
            )
        validate_tag_filters(
            domain=sub_query.domain,
            tag_filters=sub_query.tag_filters,
            query_profile_key=sub_query.structured_plan.query_profile,
        )
        plan = sub_query.structured_plan.model_copy(
            update={
                "filters": {
                    **sub_query.structured_filters,
                    **sub_query.structured_plan.filters,
                },
            }
        )
        guarded = validate_structured_plan(domain=sub_query.domain, plan=plan)
        started = time.monotonic()
        model = models.MajorOfferingRecord
        base = select(model)
        for field, value in guarded.plan.filters.items():
            if field == "province_name":
                if isinstance(value, str):
                    value = normalize_province_name(value)
                elif isinstance(value, list):
                    value = [normalize_province_name(item) for item in value]
            column = _column(field)
            if isinstance(value, dict):
                if not value or set(value) - {"between", "gte", "lte"}:
                    raise StructuredPlanGuardrailError(
                        "unsupported major offering filter operator"
                    )
                if "between" in value and (
                    not isinstance(value["between"], list) or len(value["between"]) != 2
                ):
                    raise StructuredPlanGuardrailError("between requires two bounds")
                for operator, operand in value.items():
                    if operator == "between":
                        base = base.where(column.between(*operand))
                    elif operator == "gte":
                        base = base.where(column >= operand)
                    elif operator == "lte":
                        base = base.where(column <= operand)
            elif isinstance(value, list):
                base = base.where(column.in_(value))
            elif field in {"major_name", "school_name"} and isinstance(value, str):
                base = base.where(column.icontains(value, autoescape=True))
            else:
                base = base.where(column == value)
        record_stmt = base
        if guarded.plan.order_by:
            for order in guarded.plan.order_by:
                record_stmt = record_stmt.order_by(
                    desc(_column(order.field))
                    if order.direction == "desc"
                    else asc(_column(order.field))
                )
        else:
            record_stmt = record_stmt.order_by(model.year.desc(), model.id)
        records = list(session.scalars(record_stmt.limit(guarded.limit)))
        result = RetrievalResult(
            query_id=sub_query.query_id,
            channel=sub_query.channel,
            domain=sub_query.domain,
            status=StepStatus.COMPLETED,
            result_shape="record_list",
            records=[serialize(row) for row in records],
            source_refs=[
                RetrievalSourceRef(
                    source_ref_id=f"{sub_query.query_id}-src-{i}",
                    channel=sub_query.channel,
                    domain=sub_query.domain,
                    record_ref=f"major_offering_record:{row.id}",
                    locator={"source_url": row.source_url},
                    metadata={
                        "record_id": row.id,
                        "sync_run_id": row.sync_run_id,
                        "fetched_at": row.fetched_at.isoformat(),
                        "query_id": sub_query.query_id,
                    },
                )
                for i, row in enumerate(records, 1)
            ],
            warnings=["ingested_coverage_only", "vocational_college_registration_only"],
            retrieval_meta={
                "source": "教育部政务服务平台",
                "count_semantics": "year_school_major_duration",
            },
        )
        if guarded.query_profile.key in AGGREGATION_PROFILES:
            field = (
                guarded.plan.group_by[0]
                if guarded.plan.group_by
                else AGGREGATION_PROFILES[guarded.query_profile.key]
            )
            column = _column(field)
            stmt = base.with_only_columns(
                column.label("group_value"), func.count(model.id).label("value")
            ).group_by(column)
            for order in guarded.plan.order_by:
                stmt = stmt.order_by(
                    desc(_column(order.field))
                    if order.direction == "desc"
                    else asc(_column(order.field))
                )
            if not guarded.plan.order_by:
                stmt = stmt.order_by(column)
            rows = session.execute(stmt.limit(guarded.limit)).mappings()
            result.result_shape = "aggregation"
            result.records = []
            result.aggregations = [
                StructuredAggregation(
                    group_by=[field],
                    metric="count(record)",
                    series=[
                        {
                            field: row["group_value"],
                            "value": row["value"],
                            "record_count": row["value"],
                        }
                        for row in rows
                    ],
                )
            ]
        result.elapsed_ms = (time.monotonic() - started) * 1000
        return result


def _column(field: str):
    from nexus_app.retrieval.domain_registry import MAJOR_DISTRIBUTION_FIELDS

    if field not in MAJOR_DISTRIBUTION_FIELDS:
        raise ValueError(f"unsupported major offering field {field!r}")
    return getattr(models.MajorOfferingRecord, field)


def create_major_distribution_retrieval_executor():
    return MajorDistributionRetrievalExecutor()
