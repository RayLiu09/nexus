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
    "apply_unstructured_weighted_rerank",
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

    from nexus_app.retrieval.tag_schemas import RERANK_COMBINE_OPS

    combine = (sub_query.combine or "AND").upper()
    if combine not in RERANK_COMBINE_OPS:
        return RerankDecision(
            reordered=False,
            warning_code=f"weighted_rerank_skipped_combine={combine}",
            score_stats=_score_stats(records),
        )

    # Explicit order_by wins.  Even when a rerank op is set, respect
    # the user's declared intent.
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
    # M-D — the warning code encodes the op so audit / friendly_view
    # can distinguish WEIGHTED-sum vs LINEAR-weighted vs RRF ranks.
    warning_code = (
        "weighted_rerank_applied"
        if combine == "WEIGHTED"
        else f"weighted_rerank_applied_op={combine}"
    )
    return RerankDecision(
        reordered=True,
        warning_code=warning_code,
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


# ---------------------------------------------------------------------------
# PR-7: unstructured (chunk-level) rerank
# ---------------------------------------------------------------------------
#
# Explicit gates — rerank is **never mandatory**.  Every call site
# decides on a case-by-case basis whether to run this and the decision
# is fully observable through the returned warning code.  The user asks
# ("检索/召回不应该每次都强制 rerank"): the gate hierarchy below is
# the design answer.


def apply_unstructured_weighted_rerank(
    *,
    items: list["UnstructuredItemLike"],
    sub_query: "RetrievalSubQuery",
    phase_a: "TagFilterExecutionResult",
    rerank_enabled: bool,
    profile_supports_rerank: bool,
    semantic_weight: float = 0.5,
    tag_weight: float = 0.5,
) -> RerankDecision:
    """Blend Phase A tag scores with pgvector semantic scores for unstructured hits.

    The rerank fires ONLY when every gate below passes; each gate emits
    a distinct warning code so callers can surface why rerank was
    skipped in the audit trail.  This is the deliberate "根据实际情况判断"
    behaviour — no silent mandatory rerank on every request.

    Gates (in order):

    1. **profile_supports_rerank** — only NORMALIZED_ASSET_REF anchor
       for now; OUTLINE_NODE anchor would need a chunk → outline_node
       reverse lookup that PR-7 defers.  Emits
       ``unstructured_rerank_skipped_outline_anchor``.
    2. **combine == WEIGHTED** — the user must explicitly opt in via
       the combine op.  AND/OR queries stay in pure pgvector order.
       Emits ``unstructured_rerank_skipped_combine=<op>``.
    3. **phase_a.target_scores** — nothing to weight against without
       Phase A signal.  Silent skip (matches structured pattern).
    4. **len(items) > 1** — no reordering possible below.  Emits
       ``unstructured_rerank_skipped_single_item``.
    5. **rerank_enabled** — the runtime kill-switch.  Emits
       ``unstructured_rerank_disabled_by_config`` so operators can tell
       the switch flipped a rerank off.

    When all gates pass, the item ``.score`` is replaced with
    ``semantic_weight * semantic + tag_weight * tag_score`` (tag_score
    looked up by ``item.normalized_ref_id``), items are stable-sorted
    by the blended score descending, and the warning code
    ``unstructured_rerank_applied`` is returned.
    """
    # Gate order matters — silent gates first so the "user didn't set
    # up rerank at all" happy path (no tag_filter → no target_scores)
    # stays warning-free.  Actionable gates (combine, kill-switch)
    # emit codes only when the caller did request rerank via Phase A.
    if not phase_a.target_scores:
        # Silent — Phase A didn't run or resolved to nothing to weight
        # against.  Mirrors structured executor semantics.
        return RerankDecision(
            reordered=False,
            warning_code="unstructured_rerank_skipped_no_target_scores",
            score_stats={},
        )

    if not profile_supports_rerank:
        return RerankDecision(
            reordered=False,
            warning_code="unstructured_rerank_skipped_outline_anchor",
            score_stats={},
        )

    from nexus_app.retrieval.tag_schemas import RERANK_COMBINE_OPS

    combine = (sub_query.combine or "AND").upper()
    if combine not in RERANK_COMBINE_OPS:
        return RerankDecision(
            reordered=False,
            warning_code=f"unstructured_rerank_skipped_combine={combine}",
            score_stats={},
        )

    if len(items) < 2:
        return RerankDecision(
            reordered=False,
            warning_code="unstructured_rerank_skipped_single_item",
            score_stats={},
        )

    if not rerank_enabled:
        return RerankDecision(
            reordered=False,
            warning_code="unstructured_rerank_disabled_by_config",
            score_stats={},
        )

    # Blend semantic + tag; both should be in ~[0, 1] range.
    total_weight = (semantic_weight or 0.0) + (tag_weight or 0.0)
    if total_weight <= 0:
        return RerankDecision(
            reordered=False,
            warning_code="unstructured_rerank_skipped_zero_weights",
            score_stats={},
        )

    for item in items:
        semantic = float(item.score or 0.0)
        tag_score = float(phase_a.target_scores.get(item.normalized_ref_id, 0.0))
        blended = (semantic_weight * semantic + tag_weight * tag_score) / total_weight
        item.score = blended

    items.sort(key=lambda i: i.score or 0.0, reverse=True)
    warning_code = (
        "unstructured_rerank_applied"
        if combine == "WEIGHTED"
        else f"unstructured_rerank_applied_op={combine}"
    )
    return RerankDecision(
        reordered=True,
        warning_code=warning_code,
        score_stats=_score_stats_from_items(items),
    )


def _score_stats_from_items(items: list["UnstructuredItemLike"]) -> dict[str, Any]:
    if not items:
        return {"count": 0}
    scores = [float(i.score or 0.0) for i in items]
    return {
        "count": len(scores),
        "max": max(scores),
        "min": min(scores),
        "sum": sum(scores),
    }


if TYPE_CHECKING:  # pragma: no cover
    from typing import Protocol

    class UnstructuredItemLike(Protocol):
        """Minimal shape apply_unstructured_weighted_rerank needs.

        In-tree consumers pass ``nexus_app.retrieval.schemas.UnstructuredResultItem``
        directly.  The Protocol lets tests pass a lightweight dataclass
        without importing the Pydantic model.
        """

        chunk_id: str
        normalized_ref_id: str
        score: float | None
