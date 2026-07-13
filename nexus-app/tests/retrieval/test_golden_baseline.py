"""M-C.1 / M-C.2 baseline pytest harness for retrieval golden queries.

Reads ``tests/fixtures/retrieval_golden/queries.jsonl`` and dispatches
each case down one of two execution paths:

* **M-C.1 path** — when ``prebuilt_plan`` is present, the harness
  materialises it as a ``RetrievalPlan`` and runs it through the DAG
  orchestrator directly.  No intent / planner LLM calls.
* **M-C.2 path** — when ``llm_cassette_id`` is present, the harness
  loads the cassette JSON, wraps its recorded strings in a
  ``CassetteLiteLLMClient``, and injects the client into both
  ``IntentRecognitionService`` and ``RetrievalPlannerService``.  The
  full ``RetrievalOrchestrator.run()`` loop then executes intent →
  planner → executors → DAG → audit end-to-end.

Cases with neither field are skipped (deferred to a future milestone).

Assertions and fixture seeding are shared between both paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nexus_app.ai_governance.litellm_client import CassetteLiteLLMClient
from nexus_app.retrieval.dag_orchestrator import execute_plan_as_dag
from nexus_app.retrieval.executors import (
    create_competency_retrieval_executor,
    create_unstructured_retrieval_executor,
)
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.executors.major_distribution import (
    MajorDistributionRetrievalExecutor,
)
from nexus_app.retrieval.intent import IntentRecognitionService
from nexus_app.retrieval.orchestrator import RetrievalOrchestrator
from nexus_app.retrieval.planner import RetrievalPlannerService
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
    cassette_responses,
    seed_fixture,
)


# ---------------------------------------------------------------------------
# $fixture.<key> placeholder substitution
# ---------------------------------------------------------------------------


def _resolve_fixture_placeholder(
    value: object, fixture_ids: dict[str, object] | None,
) -> object:
    """Substitute ``$fixture.<path>`` strings against the seed's return.

    Supports dotted keys and integer indexes into lists — e.g.
    ``$fixture.record_ids[0]`` or ``$fixture.first_record_id``.  Non-
    string values pass through untouched.  When ``fixture_ids`` is
    ``None`` (no fixture was seeded), the placeholder resolves to an
    empty string so the disjoint / subset assertions still work in a
    deterministic way.
    """
    if not isinstance(value, str) or not value.startswith("$fixture."):
        return value
    if fixture_ids is None:
        return ""
    import re
    path = value[len("$fixture."):]
    current: object = fixture_ids
    for segment in re.split(r"\.", path):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[(-?\d+)\])?$", segment)
        if m is None:
            return value  # malformed — leave as-is so failure is visible
        key, index = m.group(1), m.group(2)
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return value
        if current is None:
            return ""
        if index is not None:
            try:
                current = current[int(index)]
            except (IndexError, TypeError):
                return ""
    return current if current is not None else ""


def _substitute_placeholders(
    golden: GoldenQuery, fixture_ids: dict[str, object] | None,
) -> GoldenQuery:
    """Return a copy of ``golden`` with fixture placeholders resolved
    in the two record_id maps.  ``expected_rerank_order`` is intentionally
    not substituted for M-C.1/M-C.2 back-compat."""
    def _fix(mapping: dict[str, list[str]]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for qid, values in mapping.items():
            out[qid] = [
                str(_resolve_fixture_placeholder(v, fixture_ids))
                for v in values
            ]
        return out

    return golden.model_copy(update={
        "expected_record_ids_subset": _fix(
            golden.expected_record_ids_subset
        ),
        "expected_record_ids_disjoint": _fix(
            golden.expected_record_ids_disjoint
        ),
    })


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
    # Unstructured executor uses a PgvectorSearchAdapter with a
    # ``FakeEmbeddingClient`` so golden cases don't need a real LiteLLM
    # endpoint.  Semantic scoring stays deterministic (fake vectors are
    # hash-derived), and the chunk-lift path is fully exercised because
    # the adapter's chunk_ids filter is orthogonal to the embedding.
    from nexus_app.index.embedding_client import FakeEmbeddingClient
    from nexus_app.index.pgvector_search import PgvectorSearchAdapter

    fake_adapter = PgvectorSearchAdapter(
        embedding_client=FakeEmbeddingClient(),
    )
    unstructured = create_unstructured_retrieval_executor(
        search_adapter=fake_adapter,
        rerank_enabled=rerank_enabled,
    )
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

    # Cardinality-only assertion for xlsx-bootstrap cases where the
    # per-record UUID is random but the sample content guarantees a
    # minimum row count.
    for qid, minimum in golden.expected_records_at_least.items():
        result = result_by_qid.get(qid)
        if result is None:
            failures.append(f"records_at_least: no result for qid={qid}")
            continue
        count = (
            len(result.records)
            if result.records
            else len(result.items)
        )
        if count < minimum:
            failures.append(
                f"records_at_least: qid={qid} expected>={minimum} "
                f"actual={count}"
            )

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
    """Run one golden retrieval case through the appropriate path."""
    fixture_ids: dict[str, object] | None = None
    if golden.fixture_setup is not None:
        fixture_ids = seed_fixture(golden.fixture_setup, session)

    resolved = _substitute_placeholders(golden, fixture_ids)

    if resolved.prebuilt_plan is not None:
        results = _run_prebuilt_plan(resolved, session)
    elif resolved.llm_cassette_id is not None:
        results = _run_cassette(resolved, session)
    else:
        pytest.skip(
            f"{resolved.case_id}: neither prebuilt_plan nor llm_cassette_id — "
            f"case deferred to a later milestone"
        )

    failures = _apply_expectations(resolved, results)

    # Rerank order — asserted only when explicitly requested + rerank on.
    rerank_enabled = resolved.category == "rerank" and bool(
        resolved.expected_rerank_order
    )
    if rerank_enabled:
        result_by_qid = {r.query_id: r for r in results}
        for qid, expected_order in resolved.expected_rerank_order.items():
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
            "\n".join([f"[{resolved.case_id}] {resolved.notes}", *failures]),
            pytrace=False,
        )


# ---------------------------------------------------------------------------
# Execution paths
# ---------------------------------------------------------------------------


def _run_prebuilt_plan(
    golden: GoldenQuery, session,
) -> list[RetrievalResult]:
    """M-C.1 path — bypass intent + planner, execute the plan directly."""
    # Rerank gate: category=rerank golden cases either assert an explicit
    # ordering via ``expected_rerank_order`` (structured records) OR
    # signal via ``expected_warnings_contains`` that the *_rerank_applied
    # warning must surface (unstructured items — chunk order depends on
    # pgvector fake scores that are semantically noisy, so we don't
    # assert per-chunk order there).
    rerank_signalled = golden.category == "rerank" and (
        bool(golden.expected_rerank_order)
        or any(
            "rerank_applied" in w for w in golden.expected_warnings_contains
        )
    )
    executor_map = _build_executor_map(rerank_enabled=rerank_signalled)
    dispatch = _make_dispatch(executor_map)

    plan = RetrievalPlan.model_validate(golden.prebuilt_plan)
    dag_result = execute_plan_as_dag(
        session=session, plan=plan, execute_sub_query=dispatch,
    )
    return dag_result.results


def _run_cassette(
    golden: GoldenQuery, session,
) -> list[RetrievalResult]:
    """M-C.2 path — full orchestrator loop with a cassette LiteLLM client."""
    responses = cassette_responses(golden.llm_cassette_id)
    client = CassetteLiteLLMClient(responses)

    intent_service = IntentRecognitionService(
        llm_client=client,
        model_alias="cassette-intent",
        confidence_threshold=0.78,
    )
    planner_service = RetrievalPlannerService(
        llm_client=client,
        model_alias="cassette-planner",
        max_sub_queries=8,
    )

    rerank_enabled = golden.category == "rerank" and bool(
        golden.expected_rerank_order
    )
    executor_map = _build_executor_map(rerank_enabled=rerank_enabled)

    # RetrievalOrchestrator expects an executor per (channel, domain) —
    # the constructor accepts the individual executor overrides, so we
    # unpack the map.  Unstructured executor is left as the default
    # (create_unstructured_retrieval_executor) since M-C.2 cases don't
    # exercise the pgvector path yet (that's M-C.3 territory).
    orchestrator = RetrievalOrchestrator(
        intent_service=intent_service,
        planner_service=planner_service,
        major_distribution_executor=executor_map[
            (str(RetrievalChannel.STRUCTURED),
             str(BusinessDomain.MAJOR_DISTRIBUTION))
        ],
        job_demand_executor=executor_map[
            (str(RetrievalChannel.STRUCTURED),
             str(BusinessDomain.JOB_DEMAND))
        ],
        competency_executor=executor_map[
            (str(RetrievalChannel.STRUCTURED),
             str(BusinessDomain.COMPETENCY_ANALYSIS))
        ],
    )
    context_pack = orchestrator.run(session, golden.question)
    return list(context_pack.retrieval_results)
