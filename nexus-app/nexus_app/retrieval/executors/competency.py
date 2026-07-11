"""Structured retrieval executor for ability_analysis.pgsd.v1.

v1.3 PR-13b — Phase A / Phase B two-phase execution for competency
profiles anchored at ``OccupationalAbilityItem.id``:

* ``competency.ability_items_by_task`` — inner joins throughout;
  ``WHERE item.id IN (…)`` cleanly narrows results.
* ``competency.ability_items_by_category`` — same as above.
* ``competency.task_tree`` — outer joins content + item.  When
  ``tag_filters`` are present, the injected ``WHERE item.id IN (…)``
  effectively converts the outer join to an inner join for that call:
  rows with NULL item are excluded (because ``NULL NOT IN (…)``).
  Documented as intentional; call sites that need the full outer
  shape should omit tag_filters.
* ``competency.relations_by_ability`` — retains ``tag_target_type=None``.
  The relation table's ``target_id`` column is polymorphic (points at
  work_content OR ability_item OR task depending on relation_type), so
  a direct ID IN clause would be semantically wrong.  Emits
  ``tag_target_type_not_configured`` as before; a follow-up PR-13b.2
  will add ``AND target_type='ability_item'`` co-conditions.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.retrieval.rerank import apply_weighted_rerank
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


_ITEM_ANCHOR_PROFILES = frozenset({
    "competency.task_tree",
    "competency.ability_items_by_task",
    "competency.ability_items_by_category",
})


class CompetencyRetrievalExecutor:
    def __init__(
        self,
        *,
        resolver_factory: "callable | None" = None,
        rerank_enabled: bool | None = None,
    ) -> None:
        self._resolver_factory = resolver_factory or (
            lambda session: TagAssetIndexResolver(session)
        )
        self._rerank_enabled_override = rerank_enabled

    def execute(self, session: Session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        if sub_query.channel != RetrievalChannel.STRUCTURED:
            raise ValueError("CompetencyRetrievalExecutor only accepts structured sub queries")
        if sub_query.domain != BusinessDomain.COMPETENCY_ANALYSIS:
            raise ValueError("CompetencyRetrievalExecutor only accepts competency_analysis")
        if sub_query.structured_plan is None:
            raise ValueError("structured sub query requires structured_plan")

        started = time.monotonic()

        # -- Phase A: resolve tag_filters + fold structured_filters ----
        prepared_plan, phase_a = _prepare_two_phase_plan(
            session=session,
            sub_query=sub_query,
            resolver_factory=self._resolver_factory,
        )
        if phase_a.applied and not phase_a.target_ids:
            elapsed = (time.monotonic() - started) * 1000
            return _empty_result(sub_query, phase_a, elapsed)

        guarded = validate_structured_plan(
            domain=BusinessDomain.COMPETENCY_ANALYSIS,
            plan=prepared_plan,
        )
        if guarded.query_profile.key == "competency.task_tree":
            result = _execute_task_tree(session, sub_query, guarded)
        elif guarded.query_profile.key == "competency.relations_by_ability":
            result = _execute_relations(session, sub_query, guarded)
        else:
            result = _execute_ability_items(session, sub_query, guarded)
        result.elapsed_ms = (time.monotonic() - started) * 1000
        _attach_phase_a_meta(result, phase_a)
        # relations_by_ability profile still declines tag_filters — the
        # per-profile warning surfaces from Phase A's
        # ``tag_target_type_not_configured``; nothing more to do here.
        # Rerank only on record-shaped results (aggregation profiles
        # carry group_value payloads without target ids).
        if (
            guarded.query_profile.key in _ITEM_ANCHOR_PROFILES
            and result.records
        ):
            _apply_rerank(
                result=result,
                sub_query=sub_query,
                phase_a=phase_a,
                rerank_enabled=self._resolve_rerank_enabled(),
            )
        return result

    def _resolve_rerank_enabled(self) -> bool:
        if self._rerank_enabled_override is not None:
            return self._rerank_enabled_override
        from nexus_app.config import get_settings
        return bool(get_settings().effective_rerank_enabled)


def create_competency_retrieval_executor() -> CompetencyRetrievalExecutor:
    return CompetencyRetrievalExecutor()


def _dedup_append_warning(result: RetrievalResult, code: str) -> None:
    if code not in result.warnings:
        result.warnings.append(code)


# ---------------------------------------------------------------------------
# Two-phase helpers (mirror job_demand / major_distribution executors)
# ---------------------------------------------------------------------------


def _prepare_two_phase_plan(
    *,
    session: Session,
    sub_query: RetrievalSubQuery,
    resolver_factory,
) -> tuple[Any, TagFilterExecutionResult]:
    from nexus_app.audit import write_retrieval_tag_filter_audit
    from nexus_app.retrieval.domain_registry import get_query_profile

    profile = get_query_profile(
        BusinessDomain.COMPETENCY_ANALYSIS,
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
    write_retrieval_tag_filter_audit(
        session,
        sub_query=sub_query,
        profile=profile,
        phase_a=phase_a,
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
    sub_query: RetrievalSubQuery,
    phase_a: TagFilterExecutionResult,
    elapsed_ms: float,
) -> RetrievalResult:
    profile_key = sub_query.structured_plan.query_profile or ""
    if profile_key == "competency.task_tree":
        result_shape = "task_tree"
    elif profile_key == "competency.relations_by_ability":
        result_shape = "relations"
    else:
        result_shape = "ability_items"
    result = RetrievalResult(
        query_id=sub_query.query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        status=StepStatus.COMPLETED,
        result_shape=result_shape,
        elapsed_ms=elapsed_ms,
    )
    _attach_phase_a_meta(result, phase_a)
    return result


def _apply_rerank(
    *,
    result: RetrievalResult,
    sub_query: RetrievalSubQuery,
    phase_a: TagFilterExecutionResult,
    rerank_enabled: bool,
) -> None:
    """PR-13 — inject score + optional reorder for WEIGHTED combine.

    The ``id`` key on each record dict is the ability_item id — that's
    what the resolver anchored on, so per-target scores line up.  For
    ``task_tree`` records the top-level dict uses ``analysis_id``; the
    ability_item id lives under ``ability_item.id``.  We normalise
    ordering via a per-shape id extractor.
    """
    if not phase_a.target_scores:
        return
    # Inject via ``ability_item.id`` for task_tree, else ``id`` (which
    # is the ability_item's own id in ability_items_* payloads).
    profile_key = sub_query.structured_plan.query_profile or ""
    if profile_key == "competency.task_tree":
        # Task_tree records carry ability_item as a nested dict; add a
        # top-level ``id`` alias so apply_weighted_rerank picks the
        # right anchor.  Skip records without an ability_item entry.
        for record in list(result.records):
            item = record.get("ability_item")
            if isinstance(item, dict) and item.get("id"):
                record["id"] = item["id"]
    decision = apply_weighted_rerank(
        records=result.records,
        sub_query=sub_query,
        phase_a=phase_a,
        rerank_enabled=rerank_enabled,
    )
    if decision.warning_code not in result.warnings:
        result.warnings.append(decision.warning_code)
    if decision.score_stats:
        result.retrieval_meta["rerank_score_stats"] = decision.score_stats


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
        # PR-13b — Phase A's resolved target_id set arrives here bound
        # to OccupationalAbilityItem.id.  For task_tree the outer join
        # on item silently becomes an inner join (NULL rows dropped by
        # NOT IN); documented in module docstring.
        if field == TARGET_ID_IN_KEY:
            id_set = value if isinstance(value, (list, tuple, set)) else [value]
            stmt = stmt.where(models.OccupationalAbilityItem.id.in_(id_set))
            continue
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
