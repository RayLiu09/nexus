"""WEIGHTED combine op rerank helper (PR-13).

Consumed by structured executors' Phase B once records land from SQL.
Injects a ``score`` key into each record dict and, when the runtime
config permits, reorders records by score descending.

Design (per PR-13 "甲全组"):

* Score is always injected on the record dict so downstream consumers
  (Console friendly-view, LLM summarizer, audit) see the same signal
  regardless of whether reorder happened.
* The reorder itself is gated by ``settings.effective_rerank_enabled``
  — the .env.dev's ``DEFAULT_RERANKING_MODEL`` is currently unavailable
  in the model gateway, so production traffic keeps SQL order.  When
  the reranker is provisioned, flip ``RETRIEVAL_RERANK_ENABLED=true``
  and reorder starts happening without a code change.
* Users who set an explicit ``StructuredPlan.order_by`` win over
  WEIGHTED; the rerank suppresses itself and emits
  ``weighted_rerank_suppressed_by_order_by`` so the tension is visible.

Warnings surface on ``RetrievalResult.warnings`` (see PR-9):

* ``weighted_rerank_applied`` — reorder happened (positive signal).
* ``weighted_rerank_disabled_by_config`` — switch off; scores present
  but SQL order preserved.
* ``weighted_rerank_suppressed_by_order_by`` — user's order_by wins.
* ``weighted_rerank_skipped_combine=<op>`` — combine wasn't WEIGHTED.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from nexus_app.retrieval.schemas import RetrievalSubQuery
    from nexus_app.retrieval.tag_filter_execution import TagFilterExecutionResult


__all__ = [
    "RerankDecision",
    "apply_weighted_rerank",
]


@dataclass(frozen=True)
class RerankDecision:
    """Result of the rerank hook.

    ``reordered`` distinguishes the "scores injected + records reordered"
    case from "scores injected only".  Callers stash the warning code
    on ``RetrievalResult.warnings`` for observability.
    """

    reordered: bool
    warning_code: str
    score_stats: dict[str, Any]


def apply_weighted_rerank(
    *,
    records: list[dict[str, Any]],
    sub_query: "RetrievalSubQuery",
    phase_a: "TagFilterExecutionResult",
    record_id_field: str = "id",
    rerank_enabled: bool,
) -> RerankDecision:
    """Inject scores into ``records`` and optionally reorder in place.

    Parameters
    ----------
    records:
        The executor's already-fetched record dicts.  Mutated in place
        with a new ``"score"`` key.  Records whose ``record_id_field``
        value is not in ``phase_a.target_scores`` get score ``0.0`` so
        the tie-break is deterministic.
    sub_query:
        Used only for ``combine`` and ``structured_plan.order_by``.
    phase_a:
        Carries ``target_scores`` — the per-target sum of per-bucket
        max scores computed in Phase A.
    record_id_field:
        Which key on the record dict corresponds to the resolver's
        ``target_id``.  Defaults to ``"id"`` — matches every current
        structured executor's record payload shape.
    rerank_enabled:
        The runtime kill-switch.  When False, the reorder step is
        skipped even if all other preconditions hold.
    """
    # No Phase A → nothing to score against.
    if not phase_a.target_scores:
        return RerankDecision(
            reordered=False,
            warning_code="weighted_rerank_skipped_no_target_scores",
            score_stats={},
        )

    # Always inject scores so downstream sees them even when reorder is
    # suppressed.  This is the "observability + audit" promise.
    for record in records:
        rid = record.get(record_id_field)
        if not isinstance(rid, str):
            record["score"] = 0.0
            continue
        record["score"] = float(phase_a.target_scores.get(rid, 0.0))

    combine = (sub_query.combine or "AND").upper()
    if combine != "WEIGHTED":
        return RerankDecision(
            reordered=False,
            warning_code=f"weighted_rerank_skipped_combine={combine}",
            score_stats=_score_stats(records),
        )

    # Explicit order_by wins.  Even when WEIGHTED is set, respect the
    # user's declared intent.
    if (
        sub_query.structured_plan is not None
        and sub_query.structured_plan.order_by
    ):
        return RerankDecision(
            reordered=False,
            warning_code="weighted_rerank_suppressed_by_order_by",
            score_stats=_score_stats(records),
        )

    if not rerank_enabled:
        return RerankDecision(
            reordered=False,
            warning_code="weighted_rerank_disabled_by_config",
            score_stats=_score_stats(records),
        )

    # Stable sort by score desc — preserves SQL order for ties.
    records.sort(key=lambda r: r.get("score") or 0.0, reverse=True)
    return RerankDecision(
        reordered=True,
        warning_code="weighted_rerank_applied",
        score_stats=_score_stats(records),
    )


def _score_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"count": 0}
    scores = [
        float(r.get("score") or 0.0)
        for r in records
    ]
    return {
        "count": len(scores),
        "max": max(scores),
        "min": min(scores),
        "sum": sum(scores),
    }
