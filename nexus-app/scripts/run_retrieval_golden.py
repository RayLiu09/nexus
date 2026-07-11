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
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    RetrievalPlan,
    RetrievalResult,
    RetrievalSubQuery,
    StepStatus,
)
from tests.fixtures.retrieval_golden import GoldenQuery, seed_fixture


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


def _make_session():
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
    return Session()


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


def run_one(golden: GoldenQuery) -> dict[str, Any]:
    """Execute one golden query and return the flattened result envelope."""
    if golden.prebuilt_plan is None:
        return {
            "case_id": golden.case_id,
            "skipped": True,
            "reason": "prebuilt_plan missing; deferred to M-C.2",
        }

    session = _make_session()
    try:
        if golden.fixture_setup is not None:
            seed_fixture(golden.fixture_setup, session)

        rerank_enabled = golden.category == "rerank" and bool(
            golden.expected_rerank_order
        )
        executor_map = _executor_map(rerank_enabled=rerank_enabled)
        dispatch = _dispatch_for(executor_map)

        try:
            plan = RetrievalPlan.model_validate(golden.prebuilt_plan)
        except Exception as exc:  # noqa: BLE001
            return {
                "case_id": golden.case_id,
                "error": f"plan_validation_error: {type(exc).__name__}: {exc}",
                "skipped": False,
            }

        started = time.monotonic()
        dag_result = execute_plan_as_dag(
            session=session, plan=plan, execute_sub_query=dispatch,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        results = dag_result.results

        return {
            "case_id": golden.case_id,
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
    finally:
        session.close()


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
    args = parser.parse_args()

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

    envelopes = [run_one(q) for q in queries]
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
