"""PR-2 guards for v1.3 extensions on RetrievalIntent / RetrievalSubQuery /
RetrievalPlan (schemas.py).

Ensures backwards-read compatibility with pre-v1.3 payloads *and*
correct semantic validation of the new DAG / tag_filter / friendly_view
extensions.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus_app.retrieval.schemas import (
    DEFAULT_COMBINE_OP,
    MAX_DAG_DEPTH_DEFAULT,
    MAX_SUB_QUERIES_V1_3,
    BusinessDomain,
    RetrievalChannel,
    RetrievalIntent,
    RetrievalPlan,
    RetrievalSubQuery,
    StructuredPlan,
)
from nexus_app.retrieval.tag_schemas import (
    BindingSpec,
    CrossAssetTags,
    FriendlyRetrievalPlanView,
    IntentSummary,
    OverallSummary,
    TagCandidate,
    TagFilter,
)


def _make_sub(query_id: str = "q1", **overrides) -> RetrievalSubQuery:
    base = dict(
        query_id=query_id,
        channel=RetrievalChannel.STRUCTURED,
        domain=BusinessDomain.JOB_DEMAND,
        purpose="aggregation",
        query_text="北京直播电商岗位",
        structured_plan=StructuredPlan(table_profile="job_demand.v1"),
    )
    base.update(overrides)
    return RetrievalSubQuery(**base)


# ---------------------------------------------------------------------------
# Backwards read-compat — pre-v1.3 payloads still validate
# ---------------------------------------------------------------------------


class TestBackwardsCompatIntent:
    def test_pre_v1_3_intent_still_valid(self) -> None:
        intent = RetrievalIntent(
            business_domains=[BusinessDomain.JOB_DEMAND],
            retrieval_channels=[RetrievalChannel.STRUCTURED],
            question_type="aggregation",
            confidence=0.9,
        )
        assert intent.cross_asset_tags is None
        assert intent.unresolved_terms == []
        assert intent.tag_confidence is None
        assert intent.resource_hints == {}


class TestBackwardsCompatSubQuery:
    def test_pre_v1_3_sub_query_still_valid(self) -> None:
        sub = _make_sub()
        assert sub.tag_filters == {}
        assert sub.binding_map == {}
        assert sub.depends_on == []
        assert sub.combine == DEFAULT_COMBINE_OP
        assert sub.output_binding is None


class TestBackwardsCompatPlan:
    def test_pre_v1_3_plan_still_valid(self) -> None:
        plan = RetrievalPlan(
            original_query="北京直播电商",
            sub_queries=[_make_sub()],
        )
        assert plan.shared_constraints is None
        assert plan.merge_strategy == "default"
        assert plan.max_dag_depth == MAX_DAG_DEPTH_DEFAULT
        assert plan.max_sub_queries == MAX_SUB_QUERIES_V1_3
        assert plan.friendly_view is None


# ---------------------------------------------------------------------------
# RetrievalIntent — v1.3 §5.1
# ---------------------------------------------------------------------------


class TestRetrievalIntentV1_3:
    def test_populated_intent(self) -> None:
        intent = RetrievalIntent(
            business_domains=[BusinessDomain.JOB_DEMAND],
            retrieval_channels=[RetrievalChannel.STRUCTURED],
            question_type="aggregation",
            confidence=0.86,
            tag_confidence=0.9,
            unresolved_terms=["职业院校"],
            cross_asset_tags=CrossAssetTags(
                regions=[TagCandidate(value="北京市", confidence=0.94)],
                industries=[TagCandidate(value="直播电商", confidence=0.9)],
            ),
            resource_hints={"job_demand": "sql_aggregation"},
        )
        assert intent.tag_confidence == 0.9
        assert intent.unresolved_terms == ["职业院校"]
        assert intent.cross_asset_tags.regions[0].value == "北京市"

    def test_tag_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalIntent(
                business_domains=[BusinessDomain.JOB_DEMAND],
                retrieval_channels=[RetrievalChannel.STRUCTURED],
                question_type="aggregation",
                confidence=0.86,
                tag_confidence=1.2,
            )


# ---------------------------------------------------------------------------
# RetrievalSubQuery — v1.3 §5.3
# ---------------------------------------------------------------------------


class TestSubQueryV1_3:
    def test_tag_filters_accept_bucket_names(self) -> None:
        sub = _make_sub(
            tag_filters={
                "regions": TagFilter(tags=["北京市"]),
                "industries": TagFilter(tags=["直播电商"], match_strategy="l1|l1.5"),
            },
        )
        assert set(sub.tag_filters.keys()) == {"regions", "industries"}

    def test_tag_filters_reject_singular_or_unknown_keys(self) -> None:
        for bad_key in ("region", "brand_new_bucket", "REGIONS"):
            with pytest.raises(ValidationError, match="tag_filters key"):
                _make_sub(tag_filters={bad_key: TagFilter(tags=["x"])})

    def test_binding_map_ok(self) -> None:
        sub = _make_sub(
            depends_on=["q_upstream"],
            binding_map={
                "occupation_tags": BindingSpec(
                    source="$q_upstream.output.top_jobs[*].job_title",
                    as_tag_type="occupation",
                ),
            },
        )
        assert "occupation_tags" in sub.binding_map

    def test_self_reference_rejected(self) -> None:
        with pytest.raises(ValidationError, match="depends on itself"):
            _make_sub(depends_on=["q1"])  # query_id defaults to q1

    def test_combine_op_validated(self) -> None:
        _make_sub(combine="AND")
        _make_sub(combine="OR")
        _make_sub(combine="WEIGHTED")
        with pytest.raises(ValidationError, match="combine must be"):
            _make_sub(combine="XOR")


# ---------------------------------------------------------------------------
# RetrievalPlan — v1.3 §5.3
# ---------------------------------------------------------------------------


class TestRetrievalPlanV1_3:
    def test_shared_constraints_ok(self) -> None:
        plan = RetrievalPlan(
            original_query="北京直播电商",
            sub_queries=[_make_sub()],
            shared_constraints=CrossAssetTags(
                regions=[TagCandidate(value="北京市")],
            ),
        )
        assert plan.shared_constraints.regions[0].value == "北京市"

    def test_merge_strategy_evidence_chain(self) -> None:
        plan = RetrievalPlan(
            original_query="x",
            sub_queries=[_make_sub()],
            merge_strategy="evidence_chain",
        )
        assert plan.merge_strategy == "evidence_chain"

    def test_merge_strategy_unknown_rejected(self) -> None:
        with pytest.raises(ValidationError, match="merge_strategy must be"):
            RetrievalPlan(
                original_query="x",
                sub_queries=[_make_sub()],
                merge_strategy="fictional_merge",
            )

    def test_depends_on_must_reference_existing_query_id(self) -> None:
        with pytest.raises(ValidationError, match="unknown query_id"):
            RetrievalPlan(
                original_query="x",
                sub_queries=[
                    _make_sub("q1", depends_on=["q_missing"]),
                ],
            )

    def test_depends_on_ok_when_referenced_query_exists(self) -> None:
        plan = RetrievalPlan(
            original_query="x",
            sub_queries=[
                _make_sub("q1"),
                _make_sub("q2", depends_on=["q1"]),
            ],
        )
        assert plan.sub_queries[1].depends_on == ["q1"]

    def test_max_dag_depth_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalPlan(
                original_query="x",
                sub_queries=[_make_sub()],
                max_dag_depth=0,
            )
        with pytest.raises(ValidationError):
            RetrievalPlan(
                original_query="x",
                sub_queries=[_make_sub()],
                max_dag_depth=7,
            )

    def test_sub_queries_exceed_declared_max_sub_queries(self) -> None:
        """Plan-level max_sub_queries takes precedence over the schema
        cap when it's set lower."""
        with pytest.raises(ValidationError, match="exceeds declared max"):
            RetrievalPlan(
                original_query="x",
                sub_queries=[
                    _make_sub("q1"),
                    _make_sub("q2"),
                    _make_sub("q3"),
                ],
                max_sub_queries=2,
            )

    def test_friendly_view_optional(self) -> None:
        plan = RetrievalPlan(
            original_query="x",
            sub_queries=[_make_sub()],
            friendly_view=FriendlyRetrievalPlanView(
                intent_summary=IntentSummary(
                    natural_language="查询",
                    confidence=0.9,
                    confidence_level="high",
                ),
                overall=OverallSummary(
                    total_sub_queries=1,
                    max_depth=0,
                    combine_summary="AND",
                ),
            ),
        )
        assert plan.friendly_view is not None

    def test_query_id_uniqueness_still_enforced(self) -> None:
        """Regression: v1.3 additions must not break the pre-existing
        uniqueness check."""
        with pytest.raises(ValidationError, match="unique"):
            RetrievalPlan(
                original_query="x",
                sub_queries=[
                    _make_sub("dup"),
                    _make_sub("dup"),
                ],
            )
