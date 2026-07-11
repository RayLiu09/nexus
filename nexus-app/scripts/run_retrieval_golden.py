"""M-C.1 CLI — execute golden retrieval queries and export results.

Runs every ``GoldenQuery`` in the JSONL against an in-memory SQLite
session (real M-B executors + DAG orchestrator + rerank).  No LiteLLM,
no PostgreSQL — golden queries carry ``prebuilt_plan`` so the intent +
planner LLM path is bypassed.  This is the M-C.1 "baseline dry-run"
mode.  M-C.2 will add a ``--llm-cassettes`` flag for recorded LiteLLM
playback; M-C.3 will add ``--pgvector-url`` for real vector search.

Usage
-----

Run every query, write baseline to disk::

    python scripts/run_retrieval_golden.py \\
        --golden tests/fixtures/retrieval_golden/queries.jsonl \\
        --output artifacts/retrieval_baseline.jsonl

Run one case by ``case_id``::

    python scripts/run_retrieval_golden.py --case-id gq_md_record_list_zj

Output JSONL shape (one line per case)::

    {"case_id": "...", "elapsed_ms": 12.3, "pack_status": "completed",
     "warnings": [...], "sub_queries": [
        {"query_id": "q1", "status": "completed",
         "record_ids": [...], "warnings": [...], "retrieval_meta": {...}}
     ], "error": null}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add repo root to sys.path so ``tests.fixtures.*`` resolves when the
# script is invoked directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_app.ai_governance.litellm_client import CassetteLiteLLMClient
from nexus_app.database import Base
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


def _load_queries(path: Path) -> list[GoldenQuery]:
    queries: list[GoldenQuery] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                print(
                    f"{path}:{line_number}: invalid JSON: {exc}",
                    file=sys.stderr,
                )
                sys.exit(2)
            queries.append(GoldenQuery.model_validate(data))
    return queries


def _make_session(*, database_url: str | None = None):
    """Session factory — returns ``(session, cleanup_callable)``.

    - SQLite in-memory (default): fresh DDL via ``create_all``, no
      cleanup needed beyond ``session.close()``.
    - Postgres when ``database_url`` is provided: outer transaction
      wrapping the run so all seeded rows roll back at teardown.
      Assumes ``alembic upgrade head`` has been applied — no DDL runs.
    """
    if database_url:
        engine = create_engine(database_url, future=True)
        connection = engine.connect()
        transaction = connection.begin()
        Session = sessionmaker(
            bind=connection,
            autoflush=False, autocommit=False,
            expire_on_commit=False, future=True,
            join_transaction_mode="create_savepoint",
        )
        session = Session()

        def _cleanup():
            session.close()
            transaction.rollback()
            connection.close()
            engine.dispose()

        return session, _cleanup

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(
        bind=engine, autoflush=False, autocommit=False,
        expire_on_commit=False, future=True,
    )
    session = Session()
    return session, lambda: session.close()


def _executor_map(*, rerank_enabled: bool):
    job_demand = JobDemandRetrievalExecutor(rerank_enabled=rerank_enabled)
    major_dist = MajorDistributionRetrievalExecutor(
        rerank_enabled=rerank_enabled,
    )
    unstructured = create_unstructured_retrieval_executor()
    competency = create_competency_retrieval_executor()
    return {
        (str(RetrievalChannel.STRUCTURED), str(BusinessDomain.JOB_DEMAND)):
            job_demand,
        (str(RetrievalChannel.STRUCTURED), str(BusinessDomain.MAJOR_DISTRIBUTION)):
            major_dist,
        (str(RetrievalChannel.STRUCTURED), str(BusinessDomain.COMPETENCY_ANALYSIS)):
            competency,
        (str(RetrievalChannel.UNSTRUCTURED), str(BusinessDomain.COURSE_TEXTBOOK)):
            unstructured,
        (str(RetrievalChannel.UNSTRUCTURED), str(BusinessDomain.MAJOR_PROFILE)):
            unstructured,
    }


def _dispatch_for(executor_map):
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


def _record_ids(result: RetrievalResult) -> list[str]:
    if result.records:
        return [
            str(r.get("id")) for r in result.records
            if isinstance(r, dict) and r.get("id") is not None
        ]
    if result.items:
        return [item.chunk_id for item in result.items if item.chunk_id]
    return []


def _pack_status(results: list[RetrievalResult]) -> str:
    if not results:
        return "failed"
    completed = sum(1 for r in results if r.status == StepStatus.COMPLETED)
    if completed == len(results):
        return "completed"
    if completed > 0:
        return "partial"
    return "failed"


def _envelope_for(
    case_id: str,
    elapsed_ms: float,
    results: list[RetrievalResult],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "elapsed_ms": round(elapsed_ms, 2),
        "pack_status": _pack_status(results),
        "warnings": [w for r in results for w in r.warnings],
        "sub_queries": [
            {
                "query_id": r.query_id,
                "channel": str(r.channel),
                "domain": str(r.domain),
                "status": str(r.status),
                "result_shape": r.result_shape,
                "record_ids": _record_ids(r),
                "warnings": list(r.warnings),
                "retrieval_meta": dict(r.retrieval_meta),
                "error_message": r.error_message,
            }
            for r in results
        ],
        "error": None,
    }


def run_one(
    golden: GoldenQuery,
    *,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Execute one golden query and return the flattened result envelope.

    ``database_url`` — when provided, connect against that DB instead of
    the default SQLite in-memory instance.  Postgres path assumes
    ``alembic upgrade head`` has been applied.
    """
    if golden.prebuilt_plan is None and golden.llm_cassette_id is None:
        return {
            "case_id": golden.case_id,
            "skipped": True,
            "reason": "neither prebuilt_plan nor llm_cassette_id set",
        }

    session, cleanup = _make_session(database_url=database_url)
    try:
        if golden.fixture_setup is not None:
            seed_fixture(golden.fixture_setup, session)

        rerank_enabled = golden.category == "rerank" and bool(
            golden.expected_rerank_order
        )
        executor_map = _executor_map(rerank_enabled=rerank_enabled)

        started = time.monotonic()
        if golden.prebuilt_plan is not None:
            # M-C.1 path — DAG only.
            dispatch = _dispatch_for(executor_map)
            try:
                plan = RetrievalPlan.model_validate(golden.prebuilt_plan)
            except Exception as exc:  # noqa: BLE001
                return {
                    "case_id": golden.case_id,
                    "error": f"plan_validation_error: {type(exc).__name__}: {exc}",
                    "skipped": False,
                }
            dag_result = execute_plan_as_dag(
                session=session, plan=plan, execute_sub_query=dispatch,
            )
            results = dag_result.results
        else:
            # M-C.2 path — full orchestrator loop with cassette client.
            try:
                responses = cassette_responses(golden.llm_cassette_id)
            except FileNotFoundError as exc:
                return {
                    "case_id": golden.case_id,
                    "error": f"cassette_missing: {exc}",
                    "skipped": False,
                }
            client = CassetteLiteLLMClient(responses)
            intent_service = IntentRecognitionService(
                llm_client=client, model_alias="cassette-intent",
                confidence_threshold=0.78,
            )
            planner_service = RetrievalPlannerService(
                llm_client=client, model_alias="cassette-planner",
                max_sub_queries=8,
            )
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
            results = list(context_pack.retrieval_results)
        elapsed_ms = (time.monotonic() - started) * 1000
        return _envelope_for(golden.case_id, elapsed_ms, results)
    finally:
        cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--golden",
        type=Path,
        default=_REPO_ROOT
        / "tests" / "fixtures" / "retrieval_golden" / "queries.jsonl",
        help="Path to the golden queries JSONL",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Where to write the result JSONL (stdout when omitted)",
    )
    parser.add_argument(
        "--case-id", type=str, action="append", default=None,
        help="Restrict to specific case_id(s); may be repeated",
    )
    parser.add_argument(
        "--database-url", type=str, default=None,
        help=(
            "Connect against this SQLAlchemy URL instead of SQLite in-memory. "
            "Also read from $NEXUS_DATABASE_URL when the flag is omitted "
            "and $NEXUS_GOLDEN_USE_POSTGRES=1."
        ),
    )
    args = parser.parse_args()

    database_url = args.database_url
    if (
        database_url is None
        and os.getenv("NEXUS_GOLDEN_USE_POSTGRES", "").lower() in (
            "1", "true", "yes", "on",
        )
    ):
        from nexus_app.config import get_settings
        database_url = get_settings().database_url

    queries = _load_queries(args.golden)
    if args.case_id:
        wanted = set(args.case_id)
        queries = [q for q in queries if q.case_id in wanted]
        if not queries:
            print(
                f"no matching case_ids found: {sorted(wanted)}",
                file=sys.stderr,
            )
            sys.exit(2)

    envelopes = [run_one(q, database_url=database_url) for q in queries]
    lines = [
        json.dumps(env, ensure_ascii=False, default=str) for env in envelopes
    ]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(
            f"wrote {len(envelopes)} case(s) to {args.output}",
            file=sys.stderr,
        )
    else:
        for line in lines:
            print(line)


if __name__ == "__main__":
    main()
