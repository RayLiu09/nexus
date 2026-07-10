"""DAG execution engine for PR-11.

Given a ``RetrievalPlan`` with ``depends_on`` + ``binding_map`` +
``tag_filters`` binding strings, this module:

1. Topologically sorts sub_queries into layers.
2. Executes layer by layer, materialising the upstream results before
   they're needed downstream.
3. Rewrites each downstream sub_query's ``tag_filters`` in place:
   * A ``TagFilter.tags`` that is a binding string is resolved to a
     concrete ``list[str]`` before Phase A runs.
   * Every entry in ``sub_query.binding_map`` produces / augments a
     ``tag_filters[<bucket>]`` entry (bucket derived from
     ``BindingSpec.as_tag_type`` → plural bucket name).
4. Attaches binding warnings to the resulting ``RetrievalResult`` so
   the Console friendly-view can surface upstream-driven degradation.

Failure isolation:

* Unknown / failed upstream → binding resolves to empty candidates.
* Optional tag_filter with empty candidates → PR-10 I-6 kicks in.
* Non-optional tag_filter with empty candidates → PR-9/PR-10
  intersection collapse → empty sub_query result.
* DAG cycle → ``DagCycleDetected`` raised before any execution.
* DAG depth > ``plan.max_dag_depth`` → ``DagDepthExceeded`` raised.

Pre-v1.3 plans (no depends_on, no binding_map, no binding-string tags)
run identically to the old sequential path — the DAG collapses to one
layer with every sub_query independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from nexus_app.retrieval.binding_evaluator import (
    BindingContext,
    resolve_binding_expression,
)
from nexus_app.retrieval.schemas import (
    RetrievalPlan,
    RetrievalResult,
    RetrievalSubQuery,
    StepStatus,
)
from nexus_app.retrieval.tag_schemas import TagFilter

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


__all__ = [
    "DagCycleDetected",
    "DagDepthExceeded",
    "DagExecutionResult",
    "DagLayer",
    "SubQueryExecutorProtocol",
    "execute_plan_as_dag",
    "topological_layers",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DagCycleDetected(ValueError):
    """Raised when the plan contains a dependency cycle."""


class DagDepthExceeded(ValueError):
    """Raised when the number of layers exceeds ``plan.max_dag_depth``."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SubQueryExecutorProtocol(Protocol):
    def __call__(
        self,
        session: "Session",
        sub_query: RetrievalSubQuery,
    ) -> RetrievalResult:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DagLayer:
    depth: int
    sub_query_ids: tuple[str, ...]


@dataclass(frozen=True)
class DagExecutionResult:
    results: list[RetrievalResult]
    layers: tuple[DagLayer, ...]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


def topological_layers(plan: RetrievalPlan) -> tuple[DagLayer, ...]:
    """Return the DAG layers in execution order.

    Layer N contains sub_queries whose entire depends_on chain has been
    scheduled in layers < N.  Within a layer, order is stable relative
    to the original ``plan.sub_queries`` list.

    Raises
    ------
    DagCycleDetected
        On any cyclic dependency (self-cycles are caught by the
        Pydantic model validator, but multi-hop cycles land here).
    DagDepthExceeded
        When the number of layers exceeds ``plan.max_dag_depth``.
    """
    sub_query_by_id: dict[str, RetrievalSubQuery] = {
        sq.query_id: sq for sq in plan.sub_queries
    }
    # Preserve original order for stable within-layer ordering.
    order_by_id = {
        sq.query_id: idx for idx, sq in enumerate(plan.sub_queries)
    }
    remaining = set(sub_query_by_id)
    resolved: set[str] = set()
    layers: list[DagLayer] = []

    while remaining:
        ready = [
            qid for qid in remaining
            if all(dep in resolved for dep in sub_query_by_id[qid].depends_on)
        ]
        if not ready:
            unresolved = sorted(remaining)
            raise DagCycleDetected(
                f"DAG cycle detected among sub_queries {unresolved!r}"
            )
        ready.sort(key=lambda qid: order_by_id[qid])
        layers.append(DagLayer(depth=len(layers), sub_query_ids=tuple(ready)))
        resolved.update(ready)
        remaining -= set(ready)

    if len(layers) > plan.max_dag_depth:
        raise DagDepthExceeded(
            f"DAG depth {len(layers)} exceeds plan.max_dag_depth "
            f"({plan.max_dag_depth})"
        )
    return tuple(layers)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_plan_as_dag(
    *,
    session: "Session",
    plan: RetrievalPlan,
    execute_sub_query: SubQueryExecutorProtocol,
) -> DagExecutionResult:
    """Run the plan under DAG semantics.

    ``execute_sub_query`` is the per-sub_query dispatcher (usually
    :meth:`RetrievalOrchestrator._execute_sub_query`).  The caller
    controls the try/except around each execution — this module just
    orders + rewrites tag_filters.
    """
    layers = topological_layers(plan)
    results_by_qid: dict[str, RetrievalResult] = {}
    dag_warnings: list[str] = []
    ordered_results: list[RetrievalResult] = []

    for layer in layers:
        for qid in layer.sub_query_ids:
            sub_query = _sub_query_for(plan, qid)
            context = BindingContext(plan=plan, results_by_qid=results_by_qid)
            resolved_sub_query, binding_warnings = _rewrite_bindings(
                sub_query, context,
            )
            result = execute_sub_query(session, resolved_sub_query)
            for warning in binding_warnings:
                if warning not in result.warnings:
                    result.warnings.append(warning)
            results_by_qid[qid] = result
            ordered_results.append(result)

    return DagExecutionResult(
        results=ordered_results,
        layers=layers,
        warnings=dag_warnings,
    )


def _sub_query_for(plan: RetrievalPlan, qid: str) -> RetrievalSubQuery:
    for sub_query in plan.sub_queries:
        if sub_query.query_id == qid:
            return sub_query
    raise KeyError(qid)


# ---------------------------------------------------------------------------
# Binding rewrite
# ---------------------------------------------------------------------------


_TAG_TYPE_TO_BUCKET: dict[str, str] = {
    "region": "regions",
    "industry": "industries",
    "occupation": "occupations",
    "major": "majors",
    "ability": "abilities",
    "topic": "topics",
    "time_range": "time_ranges",
}


def _rewrite_bindings(
    sub_query: RetrievalSubQuery,
    context: BindingContext,
) -> tuple[RetrievalSubQuery, list[str]]:
    """Return a new sub_query with tag_filters bindings resolved."""
    warnings: list[str] = []

    # Deep-copy the tag_filters dict to avoid mutating the plan.
    new_tag_filters: dict[str, TagFilter] = {}
    for bucket, tag_filter in sub_query.tag_filters.items():
        new_tag_filters[bucket] = _resolve_tag_filter_binding(
            bucket, tag_filter, context, warnings,
        )

    # Fold binding_map entries into tag_filters.
    for map_key, spec in sub_query.binding_map.items():
        bucket = _TAG_TYPE_TO_BUCKET.get(spec.as_tag_type)
        if bucket is None:
            warnings.append(
                f"binding_map_unknown_as_tag_type:{map_key}:{spec.as_tag_type}"
            )
            continue
        result = resolve_binding_expression(spec.source, context)
        for warning in result.warnings:
            if warning not in warnings:
                warnings.append(warning)
        limited = (
            result.candidates[: spec.limit]
            if spec.limit is not None
            else result.candidates
        )
        # Merge into existing tag_filter or create.
        existing = new_tag_filters.get(bucket)
        if existing is None:
            new_tag_filters[bucket] = TagFilter(
                tags=list(limited),
                match_strategy=spec.match_strategy,
                semantic_threshold=spec.semantic_threshold,
            )
        else:
            merged_tags = _merge_tag_lists(existing, limited)
            new_tag_filters[bucket] = existing.model_copy(
                update={"tags": merged_tags}
            )

    return sub_query.model_copy(update={"tag_filters": new_tag_filters}), warnings


def _resolve_tag_filter_binding(
    bucket: str,
    tag_filter: TagFilter,
    context: BindingContext,
    warnings: list[str],
) -> TagFilter:
    """Resolve a TagFilter.tags binding str to a list; else return unchanged."""
    if isinstance(tag_filter.tags, list):
        return tag_filter
    # tags is a binding string — resolve.
    result = resolve_binding_expression(tag_filter.tags, context)
    for warning in result.warnings:
        prefixed = f"tag_filter_binding:{bucket}:{warning}"
        if prefixed not in warnings:
            warnings.append(prefixed)
    return tag_filter.model_copy(update={"tags": list(result.candidates)})


def _merge_tag_lists(
    existing: TagFilter,
    new_candidates: list[str],
) -> list[str]:
    if isinstance(existing.tags, str):
        # Existing is still a binding string — replace with the resolved
        # list (the tag_filter's own binding would have been rewritten
        # earlier in the loop; falling through here means the caller
        # explicitly wanted the binding_map to override).
        return list(new_candidates)
    combined = list(existing.tags)
    for value in new_candidates:
        if value not in combined:
            combined.append(value)
    return combined
