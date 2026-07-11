"""M-C.1 evaluator — compare a golden set to an actual run baseline.

Consumes two JSONL files:

* ``golden.jsonl`` — the ``GoldenQuery`` set with declared expectations
  (schema: :class:`tests.fixtures.retrieval_golden.schema.GoldenQuery`).
* ``actual.jsonl`` — the output of ``scripts/run_retrieval_golden.py``.

Prints a per-case pass/fail table and exits 0 iff every case passes.
The comparison rules mirror ``tests/retrieval/test_golden_baseline.py``
so the same golden set produces identical verdicts in CI (pytest) and
manual (this script) invocations.

Usage
-----

::

    python scripts/evaluate_retrieval_golden.py \\
        --golden tests/fixtures/retrieval_golden/queries.jsonl \\
        --actual artifacts/retrieval_baseline.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.fixtures.retrieval_golden import GoldenQuery


@dataclass
class CaseVerdict:
    case_id: str
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def _load_golden(path: Path) -> list[GoldenQuery]:
    entries: list[GoldenQuery] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid JSON: {exc}"
                ) from exc
            entries.append(GoldenQuery.model_validate(data))
    return entries


def _load_actual(path: Path) -> dict[str, dict[str, Any]]:
    by_case: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                continue
            envelope = json.loads(stripped)
            by_case[envelope["case_id"]] = envelope
    return by_case


def _evaluate(
    golden: GoldenQuery,
    actual: dict[str, Any] | None,
) -> CaseVerdict:
    verdict = CaseVerdict(case_id=golden.case_id)
    if actual is None:
        verdict.failures.append("actual_missing")
        return verdict
    if actual.get("skipped"):
        verdict.failures.append(
            f"actual_skipped: {actual.get('reason', 'unknown')}"
        )
        return verdict
    if actual.get("error"):
        verdict.failures.append(f"actual_error: {actual['error']}")
        return verdict

    if golden.expected_pack_status is not None:
        actual_pack = actual.get("pack_status")
        if actual_pack != golden.expected_pack_status:
            verdict.failures.append(
                f"pack_status: expected={golden.expected_pack_status!r} "
                f"actual={actual_pack!r}"
            )

    sub_queries = actual.get("sub_queries") or []
    if golden.expected_sub_query_count is not None:
        if len(sub_queries) != golden.expected_sub_query_count:
            verdict.failures.append(
                f"sub_query_count: expected={golden.expected_sub_query_count} "
                f"actual={len(sub_queries)}"
            )

    if golden.expected_channels:
        seen = {sq.get("channel") for sq in sub_queries}
        for ch in golden.expected_channels:
            if ch not in seen:
                verdict.failures.append(f"channel_missing: {ch}")

    if golden.expected_domains:
        seen = {sq.get("domain") for sq in sub_queries}
        for d in golden.expected_domains:
            if d not in seen:
                verdict.failures.append(f"domain_missing: {d}")

    all_warnings = actual.get("warnings") or []
    for w in golden.expected_warnings_contains:
        if w not in all_warnings:
            verdict.failures.append(f"warning_missing: {w}")
    for w in golden.expected_warnings_not_contains:
        if w in all_warnings:
            verdict.failures.append(f"warning_unexpected: {w}")

    by_qid = {sq["query_id"]: sq for sq in sub_queries}

    for qid, wanted in golden.expected_record_ids_subset.items():
        sq = by_qid.get(qid)
        if sq is None:
            verdict.failures.append(f"record_ids_subset: no result qid={qid}")
            continue
        actual_ids = sq.get("record_ids") or []
        for rid in wanted:
            if rid not in actual_ids:
                verdict.failures.append(
                    f"record_id_missing: qid={qid} expected={rid}"
                )

    for qid, disjoint in golden.expected_record_ids_disjoint.items():
        sq = by_qid.get(qid)
        if sq is None:
            continue
        actual_ids = sq.get("record_ids") or []
        for rid in disjoint:
            if rid in actual_ids:
                verdict.failures.append(
                    f"record_id_unexpected: qid={qid} rid={rid}"
                )

    for qid, expected_order in golden.expected_rerank_order.items():
        sq = by_qid.get(qid)
        if sq is None:
            verdict.failures.append(f"rerank_order: no result qid={qid}")
            continue
        actual_order = sq.get("record_ids") or []
        if actual_order != expected_order:
            verdict.failures.append(
                f"rerank_order: qid={qid} "
                f"expected={expected_order} actual={actual_order}"
            )

    return verdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--golden", type=Path, required=True,
        help="Path to the golden JSONL",
    )
    parser.add_argument(
        "--actual", type=Path, required=True,
        help="Path to the actual run JSONL (from run_retrieval_golden.py)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if any golden case is missing from actual",
    )
    args = parser.parse_args()

    golden_list = _load_golden(args.golden)
    actual_by_case = _load_actual(args.actual)

    verdicts = [_evaluate(g, actual_by_case.get(g.case_id)) for g in golden_list]
    if args.strict:
        extra = set(actual_by_case) - {g.case_id for g in golden_list}
        for extra_case in extra:
            verdicts.append(CaseVerdict(
                case_id=extra_case,
                failures=["extra_case_not_in_golden"],
            ))

    passed = sum(1 for v in verdicts if v.passed)
    failed = [v for v in verdicts if not v.passed]

    print("=" * 60)
    print(f"golden cases: {len(golden_list)}")
    print(f"passed:      {passed}")
    print(f"failed:      {len(failed)}")
    print("=" * 60)
    for v in failed:
        print(f"\n[{v.case_id}]")
        for f in v.failures:
            print(f"  - {f}")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
