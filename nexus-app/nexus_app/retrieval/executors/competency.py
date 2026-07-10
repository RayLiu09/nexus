"""Structured retrieval executor for ability_analysis.pgsd.v1.

PR-9 note: competency profiles do not yet declare a
``tag_target_type`` because ``task_tree`` and ``relations_by_ability``
have outer-joined or ambiguous anchor columns.  A follow-up PR will
add the "join lift" strategy that resolves tag_filters on ability
items and then narrows the outer joins.  For now, if a caller supplies
``tag_filters`` on a competency sub_query, Phase A emits
``tag_target_type_not_configured`` and the executor runs pre-v1.3
semantics with the warning attached to the result.
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
from nexus_app.retrieval.sql_guardrails import GuardedStructuredPlan, validate_structured_plan


class CompetencyRetrievalExecutor:
    def execute(self, session: Session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        if sub_query.channel != RetrievalChannel.STRUCTURED:
            raise ValueError("CompetencyRetrievalExecutor only accepts structured sub queries")
        if sub_query.domain != BusinessDomain.COMPETENCY_ANALYSIS:
            raise ValueError("CompetencyRetrievalExecutor only accepts competency_analysis")
        if sub_query.structured_plan is None:
            raise ValueError("structured sub query requires structured_plan")

        started = time.monotonic()
        guarded = validate_structured_plan(
            domain=BusinessDomain.COMPETENCY_ANALYSIS,
            plan=sub_query.structured_plan,
        )
        if guarded.query_profile.key == "competency.task_tree":
            result = _execute_task_tree(session, sub_query, guarded)
        elif guarded.query_profile.key == "competency.relations_by_ability":
            result = _execute_relations(session, sub_query, guarded)
        else:
            result = _execute_ability_items(session, sub_query, guarded)
        result.elapsed_ms = (time.monotonic() - started) * 1000
        if sub_query.tag_filters:
            _dedup_append_warning(
                result, "tag_target_type_not_configured"
            )
        return result


def create_competency_retrieval_executor() -> CompetencyRetrievalExecutor:
    return CompetencyRetrievalExecutor()


def _dedup_append_warning(result: RetrievalResult, code: str) -> None:
    if code not in result.warnings:
        result.warnings.append(code)


def _execute_task_tree(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
) -> RetrievalResult:
    stmt = _apply_filters(
        select(
            models.OccupationalAbilityAnalysis,
            models.OccupationalWorkTask,
            models.OccupationalWorkContent,
            models.OccupationalAbilityItem,
        )
        .join(
            models.OccupationalWorkTask,
            models.OccupationalWorkTask.analysis_id == models.OccupationalAbilityAnalysis.id,
        )
        .outerjoin(
            models.OccupationalWorkContent,
            models.OccupationalWorkContent.task_id == models.OccupationalWorkTask.id,
        )
        .outerjoin(
            models.OccupationalAbilityItem,
            models.OccupationalAbilityItem.task_id == models.OccupationalWorkTask.id,
        ),
        guarded.plan.filters,
    )
    stmt = _apply_order_by(stmt, guarded, default_field="task_code")
    rows = list(session.execute(stmt.limit(guarded.limit)).all())
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        status=StepStatus.COMPLETED,
        result_shape="task_tree",
        records=[_task_tree_payload(analysis, task, content, item) for analysis, task, content, item in rows],
        source_refs=_source_refs_for_task_rows(session, rows, sub_query.query_id),
    )


def _execute_ability_items(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
) -> RetrievalResult:
    stmt = _ability_item_select()
    stmt = _apply_filters(stmt, guarded.plan.filters)
    stmt = _apply_order_by(stmt, guarded, default_field="ability_code")
    if guarded.query_profile.key in {
        "competency.ability_items_by_category",
        "competency.ability_items_by_task",
    } and guarded.plan.group_by:
        group_field = guarded.plan.group_by[0]
        return _ability_item_aggregation(session, sub_query, guarded, group_field)
    rows = list(session.execute(stmt.limit(guarded.limit)).all())
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        status=StepStatus.COMPLETED,
        result_shape="ability_items",
        records=[_ability_item_payload(analysis, task, content, item) for analysis, task, content, item in rows],
        source_refs=_source_refs_for_ability_rows(session, rows, sub_query.query_id),
    )


def _ability_item_aggregation(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
    group_field: str,
) -> RetrievalResult:
    group_column = _column(group_field)
    stmt = _apply_filters(
        select(
            group_column.label("group_value"),
            func.count(models.OccupationalAbilityItem.id).label("value"),
        )
        .select_from(models.OccupationalAbilityItem)
        .join(
            models.OccupationalAbilityAnalysis,
            models.OccupationalAbilityItem.analysis_id == models.OccupationalAbilityAnalysis.id,
        )
        .join(
            models.OccupationalWorkTask,
            models.OccupationalAbilityItem.task_id == models.OccupationalWorkTask.id,
        )
        .outerjoin(
            models.OccupationalWorkContent,
            models.OccupationalAbilityItem.work_content_id == models.OccupationalWorkContent.id,
        )
        .group_by(group_column),
        guarded.plan.filters,
    )
    stmt = _apply_order_by(stmt, guarded, default_field=group_field)
    rows = session.execute(stmt.limit(guarded.limit)).mappings().all()
    source_stmt = _apply_filters(_ability_item_select(), guarded.plan.filters)
    source_stmt = _apply_order_by(source_stmt, guarded, default_field="ability_code")
    source_rows = list(session.execute(source_stmt.limit(guarded.limit)).all())
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        status=StepStatus.COMPLETED,
        result_shape="aggregation",
        aggregations=[
            StructuredAggregation(
                group_by=[group_field],
                metric="count(record)",
                series=[
                    {
                        group_field: row["group_value"],
                        "value": int(row["value"] or 0),
                    }
                    for row in rows
                ],
            )
        ],
        source_refs=_source_refs_for_ability_rows(session, source_rows, sub_query.query_id),
    )


def _execute_relations(
    session: Session,
    sub_query: RetrievalSubQuery,
    guarded: GuardedStructuredPlan,
) -> RetrievalResult:
    stmt = _apply_filters(
        select(models.OccupationalAbilityAnalysis, models.OccupationalAbilityRelation).join(
            models.OccupationalAbilityRelation,
            models.OccupationalAbilityRelation.analysis_id == models.OccupationalAbilityAnalysis.id,
        ),
        guarded.plan.filters,
    )
    stmt = _apply_order_by(stmt, guarded, default_field="relation_type")
    rows = list(session.execute(stmt.limit(guarded.limit)).all())
    return RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        status=StepStatus.COMPLETED,
        result_shape="relations",
        records=[_relation_payload(analysis, relation) for analysis, relation in rows],
        source_refs=_source_refs_for_relation_rows(session, rows, sub_query.query_id),
    )


def _ability_item_select() -> Select:
    return (
        select(
            models.OccupationalAbilityAnalysis,
            models.OccupationalWorkTask,
            models.OccupationalWorkContent,
            models.OccupationalAbilityItem,
        )
        .join(
            models.OccupationalAbilityAnalysis,
            models.OccupationalAbilityItem.analysis_id == models.OccupationalAbilityAnalysis.id,
        )
        .join(
            models.OccupationalWorkTask,
            models.OccupationalAbilityItem.task_id == models.OccupationalWorkTask.id,
        )
        .outerjoin(
            models.OccupationalWorkContent,
            models.OccupationalAbilityItem.work_content_id == models.OccupationalWorkContent.id,
        )
    )


def _apply_filters(stmt: Select, filters: dict[str, Any]) -> Select:
    for field, value in filters.items():
        column = _column(field)
        if field in {"major_name", "task_name"} and isinstance(value, str):
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
) -> Select:
    if not guarded.plan.order_by:
        return stmt.order_by(asc(_column(default_field)))
    for order in guarded.plan.order_by:
        column = _column(order.field)
        stmt = stmt.order_by(desc(column) if order.direction == "desc" else asc(column))
    return stmt


def _task_tree_payload(
    analysis: models.OccupationalAbilityAnalysis,
    task: models.OccupationalWorkTask,
    content: models.OccupationalWorkContent | None,
    item: models.OccupationalAbilityItem | None,
) -> dict[str, Any]:
    return {
        "analysis_id": analysis.id,
        "normalized_ref_id": analysis.normalized_ref_id,
        "major_name": analysis.major_name,
        "task": _task_payload(task),
        "work_content": _content_payload(content) if content else None,
        "ability_item": _item_payload(item) if item else None,
    }


def _ability_item_payload(
    analysis: models.OccupationalAbilityAnalysis,
    task: models.OccupationalWorkTask,
    content: models.OccupationalWorkContent | None,
    item: models.OccupationalAbilityItem,
) -> dict[str, Any]:
    return {
        "analysis_id": analysis.id,
        "normalized_ref_id": analysis.normalized_ref_id,
        "major_name": analysis.major_name,
        "task": _task_payload(task),
        "work_content": _content_payload(content) if content else None,
        "ability_item": _item_payload(item),
    }


def _relation_payload(
    analysis: models.OccupationalAbilityAnalysis,
    relation: models.OccupationalAbilityRelation,
) -> dict[str, Any]:
    return {
        "analysis_id": analysis.id,
        "normalized_ref_id": analysis.normalized_ref_id,
        "major_name": analysis.major_name,
        "id": relation.id,
        "source_type": relation.source_type,
        "source_id": relation.source_id,
        "relation_type": relation.relation_type,
        "target_type": relation.target_type,
        "target_id": relation.target_id,
        "confidence": float(relation.confidence) if relation.confidence is not None else None,
        "evidence": relation.evidence,
    }


def _task_payload(task: models.OccupationalWorkTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_code": task.task_code,
        "task_name": task.task_name,
        "task_description": task.task_description,
        "display_order": task.display_order,
        "trace": task.trace,
    }


def _content_payload(content: models.OccupationalWorkContent) -> dict[str, Any]:
    return {
        "id": content.id,
        "content_code": content.content_code,
        "content_name": content.content_name,
        "content_description": content.content_description,
        "display_order": content.display_order,
        "trace": content.trace,
    }


def _item_payload(item: models.OccupationalAbilityItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "ability_code": item.ability_code,
        "ability_major_category_code": item.ability_major_category_code,
        "ability_major_category_name": item.ability_major_category_name,
        "ability_sequence": item.ability_sequence,
        "ability_content": item.ability_content,
        "confidence": float(item.confidence) if item.confidence is not None else None,
        "quality_flags": item.quality_flags,
    }


def _source_refs_for_task_rows(
    session: Session,
    rows: list[tuple],
    query_id: str,
) -> list[RetrievalSourceRef]:
    refs: list[RetrievalSourceRef] = []
    for index, (analysis, task, content, item) in enumerate(rows, start=1):
        refs.append(_source_ref_for_analysis(
            session,
            analysis,
            query_id,
            index,
            record_ref=f"occupational_work_task:{task.id}",
            locator=task.trace,
            extra={
                "task_id": task.id,
                "work_content_id": content.id if content else None,
                "ability_item_id": item.id if item else None,
            },
        ))
    return refs


def _source_refs_for_ability_rows(
    session: Session,
    rows: list[tuple],
    query_id: str,
) -> list[RetrievalSourceRef]:
    return [
        _source_ref_for_analysis(
            session,
            analysis,
            query_id,
            index,
            record_ref=f"occupational_ability_item:{item.id}",
            locator=item.trace,
            extra={
                "task_id": task.id,
                "work_content_id": content.id if content else None,
                "ability_item_id": item.id,
                "ability_code": item.ability_code,
            },
        )
        for index, (analysis, task, content, item) in enumerate(rows, start=1)
    ]


def _source_refs_for_relation_rows(
    session: Session,
    rows: list[tuple],
    query_id: str,
) -> list[RetrievalSourceRef]:
    return [
        _source_ref_for_analysis(
            session,
            analysis,
            query_id,
            index,
            record_ref=f"occupational_ability_relation:{relation.id}",
            locator=relation.evidence,
            extra={
                "relation_id": relation.id,
                "relation_type": relation.relation_type,
                "source_id": relation.source_id,
                "target_id": relation.target_id,
            },
        )
        for index, (analysis, relation) in enumerate(rows, start=1)
    ]


def _source_ref_for_analysis(
    session: Session,
    analysis: models.OccupationalAbilityAnalysis,
    query_id: str,
    index: int,
    *,
    record_ref: str,
    locator: dict[str, Any],
    extra: dict[str, Any],
) -> RetrievalSourceRef:
    version = session.get(models.AssetVersion, analysis.asset_version_id)
    return RetrievalSourceRef(
        source_ref_id=f"{query_id}-src-{index}",
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        asset_id=version.asset_id if version else None,
        asset_version_id=analysis.asset_version_id,
        normalized_ref_id=analysis.normalized_ref_id,
        record_ref=record_ref,
        locator=locator or {},
        metadata={
            "analysis_id": analysis.id,
            "query_id": query_id,
            **extra,
        },
    )


COLUMNS = {
    "analysis_id": models.OccupationalAbilityAnalysis.id,
    "major_name": models.OccupationalAbilityAnalysis.major_name,
    "profile_id": models.OccupationalAbilityAnalysis.profile_id,
    "analysis_model": models.OccupationalAbilityAnalysis.analysis_model,
    "task_code": models.OccupationalWorkTask.task_code,
    "task_name": models.OccupationalWorkTask.task_name,
    "content_code": models.OccupationalWorkContent.content_code,
    "ability_major_category_code": models.OccupationalAbilityItem.ability_major_category_code,
    "ability_code": models.OccupationalAbilityItem.ability_code,
    "relation_type": models.OccupationalAbilityRelation.relation_type,
    "source_type": models.OccupationalAbilityRelation.source_type,
    "source_id": models.OccupationalAbilityRelation.source_id,
    "target_type": models.OccupationalAbilityRelation.target_type,
    "target_id": models.OccupationalAbilityRelation.target_id,
}


def _column(field: str):
    try:
        return COLUMNS[field]
    except KeyError as exc:
        raise ValueError(f"unsupported competency field {field!r}") from exc
