"""M-D — LINEAR / RRF combine op unit coverage.

Two axes:

* score aggregation semantics (``_aggregate_target_scores`` +
  ``_aggregate_rrf_scores``) at the primitive level, no fixtures
* schema plumbing (``RetrievalSubQuery.combine_weights`` / ``rrf_k``
  only valid when the matching combine op is set)

Golden runnable end-to-end coverage lives in
``tests/retrieval/test_golden_baseline.py`` via ``gq_p2_pending_rerank_linear``
/ ``_rrf`` (Phase-2 markers converted by M-D).
"""

from __future__ import annotations

import pytest

from nexus_app.retrieval.tag_filter_execution import (
    _aggregate_target_scores,
)
from nexus_app.retrieval.tag_schemas import DEFAULT_RRF_K


# ---------------------------------------------------------------------------
# LINEAR — weighted sum with per-bucket weights (default 1.0)
# ---------------------------------------------------------------------------


class TestLinearAggregation:
    """LINEAR is a superset of WEIGHTED — with no weights supplied, it
    must reproduce the WEIGHTED sum-of-max semantics exactly."""

    def test_no_weights_matches_weighted(self):
        per_bucket_scores = {
            "regions": {"t-a": 0.9, "t-b": 0.6},
            "industries": {"t-a": 0.7, "t-c": 0.8},
        }
        weighted = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False, "industries": False},
            combined_ids={"t-a", "t-b", "t-c"},
            combine="WEIGHTED",
        )
        linear = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False, "industries": False},
            combined_ids={"t-a", "t-b", "t-c"},
            combine="LINEAR",
            combine_weights=None,
        )
        assert weighted == linear
        # Sanity: t-a hits both buckets → 0.9 + 0.7 = 1.6
        assert weighted["t-a"] == pytest.approx(1.6)

    def test_weights_bias_bucket(self):
        per_bucket_scores = {
            "regions": {"t-a": 0.9},        # heavy weight
            "industries": {"t-b": 0.9},     # light weight
        }
        scores = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False, "industries": False},
            combined_ids={"t-a", "t-b"},
            combine="LINEAR",
            combine_weights={"regions": 3.0, "industries": 1.0},
        )
        # t-a is region-only weighted at 3.0 × 0.9 = 2.7
        # t-b is industry-only weighted at 1.0 × 0.9 = 0.9
        assert scores["t-a"] == pytest.approx(2.7)
        assert scores["t-b"] == pytest.approx(0.9)
        # Order: t-a must dominate.
        assert max(scores, key=scores.get) == "t-a"

    def test_missing_weight_defaults_to_one(self):
        per_bucket_scores = {
            "regions": {"t-a": 0.5},
            "topics": {"t-a": 0.5},
        }
        scores = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False, "topics": False},
            combined_ids={"t-a"},
            combine="LINEAR",
            combine_weights={"regions": 2.0},  # topics absent → weight 1.0
        )
        # 2.0 * 0.5 + 1.0 * 0.5 = 1.5
        assert scores["t-a"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# RRF — Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


class TestRRFAggregation:
    """RRF rank contributions: 1 / (k + rank).  Ids present in every
    bucket must dominate those hit in only one, regardless of raw
    score magnitude."""

    def test_shared_id_beats_single_bucket(self):
        per_bucket_scores = {
            # Ranks: t-a=1, t-b=2
            "regions": {"t-a": 0.9, "t-b": 0.6},
            # Ranks: t-a=1, t-c=2
            "industries": {"t-a": 0.9, "t-c": 0.8},
        }
        scores = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False, "industries": False},
            combined_ids={"t-a", "t-b", "t-c"},
            combine="RRF",
        )
        # k=60 default, so 1/61 ≈ 0.01639, 1/62 ≈ 0.01613
        # t-a in both at rank 1 → 2 × 1/61
        # t-b in regions rank 2 → 1/62
        # t-c in industries rank 2 → 1/62
        k = DEFAULT_RRF_K
        assert scores["t-a"] == pytest.approx(2 / (k + 1))
        assert scores["t-b"] == pytest.approx(1 / (k + 2))
        assert scores["t-c"] == pytest.approx(1 / (k + 2))
        assert scores["t-a"] > scores["t-b"]

    def test_rrf_k_override(self):
        per_bucket_scores = {"regions": {"t-a": 0.9}}
        default_scores = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False},
            combined_ids={"t-a"},
            combine="RRF",
            rrf_k=None,
        )
        custom_scores = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False},
            combined_ids={"t-a"},
            combine="RRF",
            rrf_k=1,
        )
        assert default_scores["t-a"] == pytest.approx(1 / (DEFAULT_RRF_K + 1))
        # k=1 → 1/(1+1) = 0.5, hugely different from default
        assert custom_scores["t-a"] == pytest.approx(0.5)

    def test_rrf_tie_break_stable(self):
        # Two ids with identical scores → tie broken by lex order so the
        # rank contribution is deterministic across sqlite / postgres.
        per_bucket_scores = {
            "regions": {"t-b": 0.5, "t-a": 0.5},  # ties, but t-a comes 1st
        }
        scores = _aggregate_target_scores(
            per_bucket_scores=per_bucket_scores,
            per_bucket_optional={"regions": False},
            combined_ids={"t-a", "t-b"},
            combine="RRF",
        )
        k = DEFAULT_RRF_K
        assert scores["t-a"] == pytest.approx(1 / (k + 1))
        assert scores["t-b"] == pytest.approx(1 / (k + 2))


# ---------------------------------------------------------------------------
# Schema plumbing — combine_weights / rrf_k reject mismatched combine ops
# ---------------------------------------------------------------------------


class TestSchemaGuards:
    def _make_sub_query(self, **overrides):
        from nexus_app.retrieval.schemas import (
            RetrievalChannel,
            RetrievalSubQuery,
            StructuredPlan,
        )

        return RetrievalSubQuery(
            query_id="q1",
            channel=RetrievalChannel.STRUCTURED,
            domain="job_demand",
            purpose="p",
            query_text="t",
            structured_plan=StructuredPlan(
                table_profile="job_demand.v1",
                query_profile="job_demand.record_list",
            ),
            **overrides,
        )

    def test_linear_accepts_weights(self):
        sq = self._make_sub_query(
            combine="LINEAR",
            combine_weights={"regions": 2.0, "industries": 1.5},
        )
        assert sq.combine == "LINEAR"

    def test_rrf_accepts_k(self):
        sq = self._make_sub_query(combine="RRF", rrf_k=30)
        assert sq.combine == "RRF"
        assert sq.rrf_k == 30

    def test_weights_on_non_linear_rejected(self):
        with pytest.raises(ValueError, match="combine_weights only valid"):
            self._make_sub_query(
                combine="WEIGHTED",
                combine_weights={"regions": 2.0},
            )

    def test_rrf_k_on_non_rrf_rejected(self):
        with pytest.raises(ValueError, match="rrf_k only valid"):
            self._make_sub_query(combine="WEIGHTED", rrf_k=30)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            self._make_sub_query(
                combine="LINEAR",
                combine_weights={"regions": -0.5},
            )

    def test_unknown_combine_rejected(self):
        with pytest.raises(ValueError, match="AND/OR/WEIGHTED/LINEAR/RRF"):
            self._make_sub_query(combine="BOGUS")
