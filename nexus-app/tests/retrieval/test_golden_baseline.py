"""M-C.1 baseline pytest harness for retrieval golden queries.

Reads ``tests/fixtures/retrieval_golden/queries.jsonl``, and for each
``GoldenQuery``:

1. Seeds the requested fixture into the SQLite session (via the fixture
   registry).
2. Materialises the ``prebuilt_plan`` as a real ``RetrievalPlan``.
3. Runs the orchestrator's DAG execution loop over the plan using the
   real executors (structured + unstructured stubs).  No LiteLLM or
   pgvector traffic.
4. Asserts every declared expectation, producing per-case pass/fail
   reports in the pytest output.

Extending: add another JSONL entry validated by ``GoldenQuery``, and
optionally register a new named seed function in
``fixture_registry.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nexus_app.retrieval.executors import (
    create_competency_retrieval_executor,
    create_job_demand_retrieval_executor,
    create_major_distribution_retrieval_executor,
    create_unstructured_retrieval_executor,
)
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.executors.major_distribution import (
    MajorDistributionRetrievalExecutor,
)
from nexus_app.retrieval.dag_orchestrator import execute_plan_as_dag
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalPlan,
    RetrievalResult,
    RetrievalSubQuery,
    StepStatus,
)
from tests.fixtures.retrieval_golden import (
    GoldenQuery,
    seed_fixture,
)


_QUERIES_PATH = (
    Path(__file__).parent.parent / "fixtures" / "retrieval_golden" / "queries.jsonl"
)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_queries() -> list[GoldenQuery]:
    entries: list[GoldenQuery] = []
    with _QUERIES_PATH.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{_QUERIES_PATH}:{line_number}: invalid JSON: {exc}"
                ) from exc
            entries.append(GoldenQuery.model_validate(data))
    return entries


_QUERIES = _load_queries()


# ---------------------------------------------------------------------------
# Executor factory — rerank overrides so the WEIGHTED case can assert
# ordering deterministically.
# ---------------------------------------------------------------------------


def _build_executor_map(*, rerank_enabled: bool):
    job_demand = JobDemandRetrievalExecutor(rerank_enabled=rerank_enabled)
    major_distribution = MajorDistributionRetrievalExecutor(
        rerank_enabled=rerank_enabled,
    )
    unstructured = create_unstructured_retrieval_executor()
    competency = create_competency_retrieval_executor()
    return {
        (str(RetrievalChannel.STRUCTURED), str(BusinessDomain.JOB_DEMAND)):
            job_demand,
        (str(RetrievalChannel.STRUCTURED), str(BusinessDomain.MAJOR_DISTRIBUTION)):
            major_distribution,
        (str(RetrievalChannel.STRUCTURED), str(BusinessDomain.COMPETENCY_ANALYSIS)):
            competency,
        (str(RetrievalChannel.UNSTRUCTURED), str(BusinessDomain.COURSE_TEXTBOOK)):
            unstructured,
        (str(RetrievalChannel.UNSTRUCTURED), str(BusinessDomain.MAJOR_PROFILE)):
            unstructured,
    }


def _make_dispatch(executor_map):
    def execute_sub_query(session, sub_query: RetrievalSubQuery) -> RetrievalResult:
        key = (str(sub_query.channel), str(sub_query.domain))
        executor = executor_map.get(key)
        if executor is None:
            return RetrievalResult(
                query_id=sub_query.query_id,
                channel=sub_query.channel,
                domain=sub_query.domain,
                status=StepStatus.FAILED,
                result_shape="error",
                error_message=f"unsupported_pair:{key}",
            )
        try:
            return executor.execute(session, sub_query)
        except Exception as exc:  # noqa: BLE001
            return RetrievalResult(
                query_id=sub_query.query_id,
                channel=sub_query.channel,
                domain=sub_query.domain,
                status=StepStatus.FAILED,
                result_shape="error",
                error_message=f"{type(exc).__name__}: {exc}",
            )
    return execute_sub_query


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _record_ids_for(result: RetrievalResult) -> list[str]:
    """Extract record IDs from either structured records or unstructured items."""
    if result.records:
        return [
            str(r.get("id"))
            for r in result.records
            if isinstance(r, dict) and r.get("id") is not None
        ]
    if result.items:
        return [str(item.chunk_id) for item in result.items if item.chunk_id]
    return []


def _pack_status_for(results: list[RetrievalResult]) -> str:
    if not results:
        return "failed"
    completed = sum(1 for r in results if r.status == StepStatus.COMPLETED)
    if completed == len(results):
        return "completed"
    if completed > 0:
        return "partial"
    return "failed"


def _apply_expectations(
    golden: GoldenQuery,
    results: list[RetrievalResult],
) -> list[str]:
    """Return a list of failure strings; empty list means all pass."""
    failures: list[str] = []
    result_by_qid: dict[str, RetrievalResult] = {r.query_id: r for r in results}

    if golden.expected_pack_status is not None:
        actual_status = _pack_status_for(results)
        if actual_status != golden.expected_pack_status:
            failures.append(
                f"pack_status: expected={golden.expected_pack_status!r} "
                f"actual={actual_status!r}"
            )

    if golden.expected_sub_query_count is not None:
        if len(results) != golden.expected_sub_query_count:
            failures.append(
                f"sub_query_count: expected={golden.expected_sub_query_count} "
                f"actual={len(results)}"
            )

    if golden.expected_channels:
        actual_channels = {str(r.channel) for r in results}
        for ch in golden.expected_channels:
            if ch not in actual_channels:
                failures.append(f"channel_missing: {ch}")

    if golden.expected_domains:
        actual_domains = {str(r.domain) for r in results}
        for d in golden.expected_domains:
            if d not in actual_domains:
                failures.append(f"domain_missing: {d}")

    if golden.expected_result_shapes:
        actual_shapes = {r.result_shape for r in results if r.result_shape}
        for s in golden.expected_result_shapes:
            if s not in actual_shapes:
                failures.append(f"result_shape_missing: {s}")

    # Warnings — flattened across all sub_queries.
    all_warnings: list[str] = []
    for r in results:
        all_warnings.extend(r.warnings)
    for w in golden.expected_warnings_contains:
        if w not in all_warnings:
            failures.append(f"warning_missing: {w}")
    for w in golden.expected_warnings_not_contains:
        if w in all_warnings:
            failures.append(f"warning_unexpected: {w}")

    # Record IDs
    for qid, wanted in golden.expected_record_ids_subset.items():
        result = result_by_qid.get(qid)
        if result is None:
            failures.append(f"record_ids_subset: no result for qid={qid}")
            continue
        actual_ids = _record_ids_for(result)
        for rid in wanted:
            if rid not in actual_ids:
                failures.append(
                    f"record_id_missing: qid={qid} expected={rid} "
                    f"actual={actual_ids}"
                )

    for qid, disjoint in golden.expected_record_ids_disjoint.items():
        result = result_by_qid.get(qid)
        if result is None:
            continue
        actual_ids = _record_ids_for(result)
        for rid in disjoint:
            if rid in actual_ids:
                failures.append(
                    f"record_id_unexpected: qid={qid} rid={rid}"
                )

    return failures


# ---------------------------------------------------------------------------
# Test entry — one parametrised case per JSONL entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "golden",
    _QUERIES,
    ids=[q.case_id for q in _QUERIES],
)
def test_golden_query(golden: GoldenQuery, session):
    """Run one golden retrieval case through the executor + DAG path."""
    if golden.fixture_setup is not None:
        seed_fixture(golden.fixture_setup, session)

    if golden.prebuilt_plan is None:
        pytest.skip(
            f"{golden.case_id}: prebuilt_plan missing "
            f"— intent + planner integration lands in M-C.2"
        )

    # Rerank cases: enable the switch at executor level so ordering is
    # deterministic under test.  Default OFF for all other cases mirrors
    # production behavior.
    rerank_enabled = golden.category == "rerank" and bool(
        golden.expected_rerank_order
    )
    executor_map = _build_executor_map(rerank_enabled=rerank_enabled)
    dispatch = _make_dispatch(executor_map)

    plan = RetrievalPlan.model_validate(golden.prebuilt_plan)
    dag_result = execute_plan_as_dag(
        session=session,
        plan=plan,
        execute_sub_query=dispatch,
    )
    results = dag_result.results

    failures = _apply_expectations(golden, results)

    # Rerank order — asserted only when explicitly requested + rerank on.
    if rerank_enabled:
        result_by_qid = {r.query_id: r for r in results}
        for qid, expected_order in golden.expected_rerank_order.items():
            result = result_by_qid.get(qid)
            if result is None:
                failures.append(f"rerank_order: no result for qid={qid}")
                continue
            actual_order = [
                r.get("id") for r in result.records if isinstance(r, dict)
            ]
            if actual_order != expected_order:
                failures.append(
                    f"rerank_order: qid={qid} "
                    f"expected={expected_order} actual={actual_order}"
                )

    if failures:
        pytest.fail(
            "\n".join([f"[{golden.case_id}] {golden.notes}", *failures]),
            pytrace=False,
        )
