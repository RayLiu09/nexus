"""PR-11 guards for DAG execution engine + BindingSpec evaluator."""

from __future__ import annotations

from typing import Any

import pytest

from nexus_app.retrieval.binding_evaluator import (
    BindingContext,
    resolve_binding_expression,
)
from nexus_app.retrieval.dag_orchestrator import (
    DagCycleDetected,
    DagDepthExceeded,
    execute_plan_as_dag,
    topological_layers,
)
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalPlan,
    RetrievalResult,
    RetrievalSubQuery,
    StepStatus,
    StructuredPlan,
    UnstructuredPlan,
)
from nexus_app.retrieval.tag_schemas import (
    BindingSpec,
    CrossAssetTags,
    TagCandidate,
    TagFilter,
)


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------


def _sub_query(
    qid: str,
    *,
    depends_on: list[str] | None = None,
    tag_filters: dict[str, dict[str, Any]] | None = None,
    binding_map: dict[str, dict[str, Any]] | None = None,
    domain: BusinessDomain = BusinessDomain.JOB_DEMAND,
    channel: RetrievalChannel = RetrievalChannel.STRUCTURED,
) -> RetrievalSubQuery:
    payload: dict[str, Any] = {
        "query_id": qid,
        "channel": channel,
        "domain": domain,
        "purpose": "test",
        "query_text": f"query {qid}",
    }
    if channel == RetrievalChannel.STRUCTURED:
        payload["structured_plan"] = StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.record_list",
        ).model_dump()
    else:
        payload["unstructured_plan"] = UnstructuredPlan(top_k=5).model_dump()
    if depends_on:
        payload["depends_on"] = depends_on
    if tag_filters:
        payload["tag_filters"] = tag_filters
    if binding_map:
        payload["binding_map"] = binding_map
    return RetrievalSubQuery.model_validate(payload)


def _plan(
    sub_queries: list[RetrievalSubQuery],
    *,
    shared_constraints: CrossAssetTags | None = None,
    max_dag_depth: int = 3,
) -> RetrievalPlan:
    return RetrievalPlan(
        original_query="test",
        sub_queries=sub_queries,
        shared_constraints=shared_constraints,
        max_dag_depth=max_dag_depth,
    )


# ---------------------------------------------------------------------------
# TopologicalLayers
# ---------------------------------------------------------------------------


class TestTopologicalLayers:
    def test_no_dependencies_single_layer(self):
        plan = _plan([
            _sub_query("q1"),
            _sub_query("q2"),
            _sub_query("q3"),
        ])
        layers = topological_layers(plan)
        assert len(layers) == 1
        assert layers[0].sub_query_ids == ("q1", "q2", "q3")

    def test_chain_becomes_layered(self):
        plan = _plan([
            _sub_query("q1"),
            _sub_query("q2", depends_on=["q1"]),
            _sub_query("q3", depends_on=["q2"]),
        ])
        layers = topological_layers(plan)
        assert [l.sub_query_ids for l in layers] == [("q1",), ("q2",), ("q3",)]

    def test_diamond_topology(self):
        plan = _plan([
            _sub_query("q1"),
            _sub_query("q2", depends_on=["q1"]),
            _sub_query("q3", depends_on=["q1"]),
            _sub_query("q4", depends_on=["q2", "q3"]),
        ])
        layers = topological_layers(plan)
        assert [l.sub_query_ids for l in layers] == [
            ("q1",), ("q2", "q3"), ("q4",),
        ]

    def test_cycle_detected(self):
        # Two-node cycle — the model validator forbids self-loops but
        # allows a q1 → q2 → q1 shape at construction time.
        plan = _plan([
            _sub_query("q1", depends_on=["q2"]),
            _sub_query("q2", depends_on=["q1"]),
        ])
        with pytest.raises(DagCycleDetected):
            topological_layers(plan)

    def test_depth_exceeded(self):
        plan = _plan([
            _sub_query("q1"),
            _sub_query("q2", depends_on=["q1"]),
            _sub_query("q3", depends_on=["q2"]),
            _sub_query("q4", depends_on=["q3"]),
        ], max_dag_depth=3)
        with pytest.raises(DagDepthExceeded):
            topological_layers(plan)


# ---------------------------------------------------------------------------
# BindingExpression — $shared
# ---------------------------------------------------------------------------


class TestBindingSharedResolver:
    def test_shared_bucket_returns_values(self):
        shared = CrossAssetTags(
            industries=[TagCandidate(value="直播电商"), TagCandidate(value="生鲜")],
        )
        plan = _plan([_sub_query("q1")], shared_constraints=shared)
        ctx = BindingContext(plan=plan, results_by_qid={})
        result = resolve_binding_expression("$shared.industries", ctx)
        assert result.candidates == ["直播电商", "生鲜"]
        assert result.warnings == []

    def test_shared_explicit_value_selector(self):
        shared = CrossAssetTags(
            regions=[TagCandidate(value="北京市")],
        )
        plan = _plan([_sub_query("q1")], shared_constraints=shared)
        ctx = BindingContext(plan=plan, results_by_qid={})
        result = resolve_binding_expression("$shared.regions[*].value", ctx)
        assert result.candidates == ["北京市"]

    def test_shared_not_configured(self):
        plan = _plan([_sub_query("q1")])
        ctx = BindingContext(plan=plan, results_by_qid={})
        result = resolve_binding_expression("$shared.regions", ctx)
        assert "binding_shared_not_configured" in result.warnings
        assert result.candidates == []

    def test_shared_unknown_bucket(self):
        shared = CrossAssetTags()
        plan = _plan([_sub_query("q1")], shared_constraints=shared)
        ctx = BindingContext(plan=plan, results_by_qid={})
        result = resolve_binding_expression("$shared.not_a_bucket", ctx)
        assert any(
            w.startswith("binding_expression_invalid:unknown_field")
            for w in result.warnings
        )


# ---------------------------------------------------------------------------
# BindingExpression — $<qid>
# ---------------------------------------------------------------------------


class TestBindingUpstreamResolver:
    def _upstream_result(self, records: list[dict[str, Any]]) -> RetrievalResult:
        return RetrievalResult(
            query_id="q_job",
            channel=RetrievalChannel.STRUCTURED,
            domain=BusinessDomain.JOB_DEMAND,
            status=StepStatus.COMPLETED,
            result_shape="record_list",
            records=records,
        )

    def test_upstream_records_field_extracted(self):
        upstream = self._upstream_result([
            {"id": "r1", "city": "北京市"},
            {"id": "r2", "city": "上海市"},
        ])
        plan = _plan([_sub_query("q_x")])
        ctx = BindingContext(plan=plan, results_by_qid={"q_job": upstream})
        result = resolve_binding_expression(
            "$q_job.output.records[*].city", ctx,
        )
        assert result.candidates == ["北京市", "上海市"]

    def test_upstream_records_dedupes(self):
        upstream = self._upstream_result([
            {"city": "北京市"}, {"city": "北京市"}, {"city": "上海市"},
        ])
        plan = _plan([_sub_query("q_x")])
        ctx = BindingContext(plan=plan, results_by_qid={"q_job": upstream})
        result = resolve_binding_expression(
            "$q_job.output.records[*].city", ctx,
        )
        assert result.candidates == ["北京市", "上海市"]

    def test_upstream_missing(self):
        plan = _plan([_sub_query("q_x")])
        ctx = BindingContext(plan=plan, results_by_qid={})
        result = resolve_binding_expression(
            "$q_missing.output.records[*].city", ctx,
        )
        assert "binding_upstream_missing:q_missing" in result.warnings
        assert result.upstream_qid == "q_missing"

    def test_upstream_failed(self):
        failed = RetrievalResult(
            query_id="q_job",
            channel=RetrievalChannel.STRUCTURED,
            domain=BusinessDomain.JOB_DEMAND,
            status=StepStatus.FAILED,
            result_shape="error",
        )
        plan = _plan([_sub_query("q_x")])
        ctx = BindingContext(plan=plan, results_by_qid={"q_job": failed})
        result = resolve_binding_expression(
            "$q_job.output.records[*].city", ctx,
        )
        assert "binding_upstream_failed:q_job" in result.warnings
        assert result.candidates == []

    def test_upstream_empty_records(self):
        upstream = self._upstream_result([])
        plan = _plan([_sub_query("q_x")])
        ctx = BindingContext(plan=plan, results_by_qid={"q_job": upstream})
        result = resolve_binding_expression(
            "$q_job.output.records[*].city", ctx,
        )
        # Empty upstream — candidates empty + warning
        assert result.candidates == []
        assert any(
            w.startswith("binding_upstream_empty:") for w in result.warnings
        )

    def test_upstream_field_missing_in_records(self):
        upstream = self._upstream_result([{"id": "r1"}])  # no "city"
        plan = _plan([_sub_query("q_x")])
        ctx = BindingContext(plan=plan, results_by_qid={"q_job": upstream})
        result = resolve_binding_expression(
            "$q_job.output.records[*].city", ctx,
        )
        assert result.candidates == []


# ---------------------------------------------------------------------------
# DAG execution — end-to-end with a stub executor
# ---------------------------------------------------------------------------


class _RecordingExecutor:
    """Executor that captures the sub_query it saw + returns a canned result."""

    def __init__(self, canned: dict[str, RetrievalResult]):
        self._canned = canned
        self.seen: list[RetrievalSubQuery] = []

    def __call__(self, session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        self.seen.append(sub_query)
        return self._canned.get(
            sub_query.query_id,
            RetrievalResult(
                query_id=sub_query.query_id,
                channel=sub_query.channel,
                domain=sub_query.domain,
                status=StepStatus.COMPLETED,
                result_shape="record_list",
            ),
        )


class TestDagExecution:
    def test_binding_string_resolved_before_downstream_runs(self):
        upstream_result = RetrievalResult(
            query_id="q_job",
            channel=RetrievalChannel.STRUCTURED,
            domain=BusinessDomain.JOB_DEMAND,
            status=StepStatus.COMPLETED,
            result_shape="record_list",
            records=[{"city": "北京市"}, {"city": "上海市"}],
        )
        plan = _plan([
            _sub_query("q_job"),
            _sub_query(
                "q_ability",
                depends_on=["q_job"],
                tag_filters={
                    "regions": TagFilter(
                        tags="$q_job.output.records[*].city",
                        match_strategy="l1|l1.5",
                    ).model_dump(),
                },
            ),
        ])
        executor = _RecordingExecutor({"q_job": upstream_result})
        dag_result = execute_plan_as_dag(
            session=None, plan=plan, execute_sub_query=executor,
        )
        # Verify execution order (q_job before q_ability)
        assert [sq.query_id for sq in executor.seen] == ["q_job", "q_ability"]
        # Verify q_ability's tag_filter was rewritten
        q_ability_seen = executor.seen[1]
        assert q_ability_seen.tag_filters["regions"].tags == ["北京市", "上海市"]

    def test_binding_map_appends_bucket(self):
        upstream_result = RetrievalResult(
            query_id="q_job",
            channel=RetrievalChannel.STRUCTURED,
            domain=BusinessDomain.JOB_DEMAND,
            status=StepStatus.COMPLETED,
            result_shape="record_list",
            records=[{"industry_name": "直播电商"}],
        )
        plan = _plan([
            _sub_query("q_job"),
            _sub_query(
                "q_x",
                depends_on=["q_job"],
                binding_map={
                    "industries_from_jobs": BindingSpec(
                        source="$q_job.output.records[*].industry_name",
                        as_tag_type="industry",
                        match_strategy="l1|l1.5",
                    ).model_dump(),
                },
            ),
        ])
        executor = _RecordingExecutor({"q_job": upstream_result})
        execute_plan_as_dag(
            session=None, plan=plan, execute_sub_query=executor,
        )
        q_x_seen = executor.seen[1]
        assert q_x_seen.tag_filters["industries"].tags == ["直播电商"]

    def test_upstream_missing_warning_attached(self):
        plan = _plan([
            _sub_query(
                "q_ability",
                tag_filters={
                    "regions": TagFilter(
                        tags="$q_missing.output.records[*].city",
                        match_strategy="l1|l1.5",
                    ).model_dump(),
                },
            ),
        ])
        executor = _RecordingExecutor({})
        dag_result = execute_plan_as_dag(
            session=None, plan=plan, execute_sub_query=executor,
        )
        # Warning attached to the executed sub_query's result.
        assert len(dag_result.results) == 1
        warnings = dag_result.results[0].warnings
        assert any(
            "binding_upstream_missing" in w for w in warnings
        )
        # And the tag_filter's tags are empty.
        q_seen = executor.seen[0]
        assert q_seen.tag_filters["regions"].tags == []

    def test_pre_v1_3_plan_still_runs(self):
        plan = _plan([
            _sub_query("q1"),
            _sub_query("q2"),
        ])
        executor = _RecordingExecutor({})
        dag_result = execute_plan_as_dag(
            session=None, plan=plan, execute_sub_query=executor,
        )
        assert [r.query_id for r in dag_result.results] == ["q1", "q2"]
        assert len(dag_result.layers) == 1
