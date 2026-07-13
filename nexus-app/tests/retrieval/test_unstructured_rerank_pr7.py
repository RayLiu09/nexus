"""PR-7 guards for the unstructured executor rerank pipeline.

Contract mirror of the PR-13 structured tests, but scoped to
``apply_unstructured_weighted_rerank`` — the helper the unstructured
executor plumbs into after Phase A + pgvector search.  The design
promise is "根据实际情况判断是否需要 rerank 流程" — no silent mandatory
rerank on every request — so every gate has an explicit test.

Gate ladder (in the order the helper checks them):

1. profile_supports_rerank (only NORMALIZED_ASSET_REF anchor for PR-7)
2. combine == WEIGHTED
3. phase_a.target_scores non-empty
4. len(items) >= 2
5. rerank_enabled runtime kill-switch
6. positive-weight sanity
"""

from __future__ import annotations

from dataclasses import dataclass

from nexus_app.retrieval.rerank import (
    RerankDecision,
    apply_unstructured_weighted_rerank,
)
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalSubQuery,
    UnstructuredPlan,
)
from nexus_app.retrieval.tag_filter_execution import TagFilterExecutionResult


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class _Item:
    """Minimal shape matching `UnstructuredItemLike` protocol.

    Kept intentionally lightweight so the tests don't touch the
    Pydantic model — the helper only ever reads normalized_ref_id +
    score and writes score back.
    """

    chunk_id: str
    normalized_ref_id: str
    score: float | None


def _sub_query(
    *,
    combine: str = "AND",
    query_id: str = "q1",
) -> RetrievalSubQuery:
    plan = UnstructuredPlan(top_k=5, query_profile="semantic_chunk")
    return RetrievalSubQuery(
        query_id=query_id,
        channel=RetrievalChannel.UNSTRUCTURED,
        domain=BusinessDomain.COURSE_TEXTBOOK,
        purpose="test",
        query_text="教材内容",
        unstructured_plan=plan,
        combine=combine,
    )


def _phase_a_with_scores(scores: dict[str, float]) -> TagFilterExecutionResult:
    # ``applied`` is a computed property (``target_ids is not None``);
    # passing a non-None set is enough to mark Phase A as active.
    return TagFilterExecutionResult(
        target_ids=set(scores),
        target_scores=dict(scores),
    )


def _phase_a_empty() -> TagFilterExecutionResult:
    return TagFilterExecutionResult(target_ids=None)


# ---------------------------------------------------------------------------
# Gate 1: profile_supports_rerank
# ---------------------------------------------------------------------------


def test_outline_anchor_skips_with_distinct_warning():
    items = [_Item("c1", "ref-a", 0.4), _Item("c2", "ref-b", 0.5)]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0, "ref-b": 0.5}),
        rerank_enabled=True,
        profile_supports_rerank=False,
    )
    assert isinstance(decision, RerankDecision)
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_skipped_outline_anchor"
    # Scores must remain untouched so the caller can still surface
    # pgvector's original ranking.
    assert items[0].score == 0.4
    assert items[1].score == 0.5


# ---------------------------------------------------------------------------
# Gate 2: combine op
# ---------------------------------------------------------------------------


def test_and_combine_skips_without_reorder():
    items = [_Item("c1", "ref-a", 0.3), _Item("c2", "ref-b", 0.6)]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="AND"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0, "ref-b": 0.5}),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_skipped_combine=AND"
    # Original semantic order preserved (c1 before c2).
    assert [i.chunk_id for i in items] == ["c1", "c2"]


def test_or_combine_skips_without_reorder():
    items = [_Item("c1", "ref-a", 0.7), _Item("c2", "ref-b", 0.2)]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="OR"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0, "ref-b": 0.5}),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_skipped_combine=OR"


# ---------------------------------------------------------------------------
# Gate 3: phase_a.target_scores
# ---------------------------------------------------------------------------


def test_no_target_scores_skips_silently():
    """Phase A never ran (no tag_filters) — pgvector order is the only signal."""
    items = [_Item("c1", "ref-a", 0.3), _Item("c2", "ref-b", 0.7)]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_empty(),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_skipped_no_target_scores"


# ---------------------------------------------------------------------------
# Gate 4: len(items) >= 2
# ---------------------------------------------------------------------------


def test_single_item_skips():
    items = [_Item("c1", "ref-a", 0.5)]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0}),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_skipped_single_item"


def test_zero_items_skips():
    """Empty result set — nothing to score against, silent no-op."""
    decision = apply_unstructured_weighted_rerank(
        items=[],
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0}),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_skipped_single_item"


# ---------------------------------------------------------------------------
# Gate 5: kill switch
# ---------------------------------------------------------------------------


def test_kill_switch_disabled_by_config():
    """Operators flipped rerank off at runtime — no reorder even though
    every other precondition holds."""
    items = [_Item("c1", "ref-a", 0.3), _Item("c2", "ref-b", 0.6)]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0, "ref-b": 0.5}),
        rerank_enabled=False,
        profile_supports_rerank=True,
    )
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_disabled_by_config"
    # Original pgvector order preserved so the user still gets a
    # deterministic result set.
    assert [i.chunk_id for i in items] == ["c1", "c2"]


# ---------------------------------------------------------------------------
# Gate 6: positive-weight sanity
# ---------------------------------------------------------------------------


def test_zero_weights_short_circuit():
    items = [_Item("c1", "ref-a", 0.3), _Item("c2", "ref-b", 0.6)]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0, "ref-b": 0.5}),
        rerank_enabled=True,
        profile_supports_rerank=True,
        semantic_weight=0.0,
        tag_weight=0.0,
    )
    assert decision.reordered is False
    assert decision.warning_code == "unstructured_rerank_skipped_zero_weights"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_weighted_rerank_reorders_when_all_gates_pass():
    """
    Two chunks, two refs.  c2 sits ahead in pgvector order (0.6 > 0.4)
    but ref-a has a much higher tag score (1.0 vs 0.1).  With equal
    50/50 weights, ref-a's blended score wins so c1 floats up.

      blended(c1) = 0.5 * 0.4 + 0.5 * 1.0 = 0.7
      blended(c2) = 0.5 * 0.6 + 0.5 * 0.1 = 0.35
    """
    items = [
        _Item("c2", "ref-b", 0.6),  # pgvector winner
        _Item("c1", "ref-a", 0.4),  # tag winner
    ]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_with_scores({"ref-a": 1.0, "ref-b": 0.1}),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    assert decision.reordered is True
    assert decision.warning_code == "unstructured_rerank_applied"
    # c1 (tag-boosted ref-a) climbs to the top.
    assert [i.chunk_id for i in items] == ["c1", "c2"]
    # Item scores are the blended values.
    assert abs((items[0].score or 0.0) - 0.7) < 1e-6
    assert abs((items[1].score or 0.0) - 0.35) < 1e-6
    # Stats reflect the blended distribution, not the pre-rerank scores.
    assert decision.score_stats["count"] == 2
    assert abs(decision.score_stats["max"] - 0.7) < 1e-6


def test_stable_sort_preserves_pgvector_order_on_score_tie():
    """When blended scores tie, pgvector's original order must survive."""
    items = [
        _Item("c1", "ref-a", 0.5),
        _Item("c2", "ref-b", 0.5),
        _Item("c3", "ref-a", 0.5),
    ]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        # Same tag score across all refs → blended scores tie.
        phase_a=_phase_a_with_scores({"ref-a": 0.5, "ref-b": 0.5}),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    assert decision.reordered is True
    assert [i.chunk_id for i in items] == ["c1", "c2", "c3"]


def test_missing_target_score_falls_back_to_zero():
    """A chunk whose ref has no Phase A score gets tag_score=0 (not skipped),
    so it drops relative to a ref with a positive tag score."""
    items = [
        _Item("c1", "ref-known", 0.5),
        _Item("c2", "ref-unknown", 0.9),
    ]
    decision = apply_unstructured_weighted_rerank(
        items=items,
        sub_query=_sub_query(combine="WEIGHTED"),
        phase_a=_phase_a_with_scores({"ref-known": 1.0}),
        rerank_enabled=True,
        profile_supports_rerank=True,
    )
    # blended(c1) = 0.5 * 0.5 + 0.5 * 1.0 = 0.75
    # blended(c2) = 0.5 * 0.9 + 0.5 * 0.0 = 0.45
    assert decision.reordered is True
    assert [i.chunk_id for i in items] == ["c1", "c2"]
