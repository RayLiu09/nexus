"""Evaluate exported v1.0 retrieval/recall runs against a JSONL question set.

The evaluator is offline by design: it does not call LiteLLM, PostgreSQL, or
the retrieval APIs. It consumes exported run payloads and reports deterministic
quality/safety metrics suitable for CI artifacts or pilot acceptance review.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FORBIDDEN_SQL_KEYS = {"sql", "raw_sql", "statement", "query", "text_sql"}
FORBIDDEN_SQL_PATTERNS = (
    "select ",
    "insert ",
    "update ",
    "delete ",
    "drop ",
    "alter ",
    ";",
    "--",
    "/*",
)
DEFAULT_THRESHOLDS = {
    "intent_accuracy": 0.80,
    "low_confidence_block_rate": 1.00,
    "plan_accuracy": 0.80,
    "unstructured_recall_at_k": 0.60,
    "structured_correctness": 0.90,
    "sql_guardrail_pass_rate": 1.00,
    "citation_completeness": 0.95,
    "markdown_faithfulness_proxy": 0.95,
}


@dataclass
class CaseEvaluation:
    case_id: str
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(self.checks.values()) if self.checks else False

    @property
    def failed_checks(self) -> list[str]:
        return [name for name, ok in self.checks.items() if not ok]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: JSONL record must be an object")
            records.append(record)
    return records


def evaluate(
    questions: list[dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    result_by_id = {_result_question_id(result): result for result in results}
    case_reports = [
        _evaluate_case(question, result_by_id.get(str(question.get("id", ""))))
        for question in questions
    ]
    metrics = _aggregate_metrics(case_reports, results, questions)
    threshold_failures = _threshold_failures(metrics, thresholds)
    failures = [
        {
            "case_id": report.case_id,
            "checks": report.failed_checks,
            "details": report.details,
        }
        for report in case_reports
        if not report.passed
    ]
    passed_cases = sum(1 for report in case_reports if report.passed)
    summary = {
        "total_cases": len(case_reports),
        "passed_cases": passed_cases,
        "failed_cases": len(case_reports) - passed_cases,
        "overall_pass_rate": _ratio(passed_cases, len(case_reports)),
        "threshold_failures": threshold_failures,
    }
    return {
        "summary": summary,
        "metrics": metrics,
        "failures": failures,
        "cases": [
            {
                "case_id": report.case_id,
                "passed": report.passed,
                "checks": report.checks,
                "details": report.details,
            }
            for report in case_reports
        ],
    }


def _evaluate_case(question: dict[str, Any], result: dict[str, Any] | None) -> CaseEvaluation:
    case_id = str(question.get("id", ""))
    report = CaseEvaluation(case_id=case_id)
    if result is None:
        report.checks = {
            "run_result_present": False,
            "intent_accuracy": False,
            "low_confidence_block": False,
            "plan_accuracy": False,
            "unstructured_recall_at_k": False,
            "structured_correctness": False,
            "sql_guardrail": False,
            "citation_completeness": False,
            "markdown_faithfulness_proxy": False,
        }
        report.details["missing_result"] = True
        return report

    expect_clarification = bool(question.get("expect_clarification", False))
    report.checks["run_result_present"] = True
    report.checks["intent_accuracy"] = _check_intent(question, result)
    report.checks["low_confidence_block"] = (
        _check_low_confidence_block(result) if expect_clarification else True
    )
    report.checks["plan_accuracy"] = (
        True if expect_clarification else _check_plan(question, result)
    )
    report.checks["unstructured_recall_at_k"] = _check_unstructured_recall(question, result)
    report.checks["structured_correctness"] = _check_structured_correctness(question, result)
    report.checks["sql_guardrail"] = _check_sql_guardrail(result)
    report.checks["citation_completeness"] = _check_citation_completeness(result)
    report.checks["markdown_faithfulness_proxy"] = _check_markdown_faithfulness(result)
    report.details = _case_details(question, result)
    return report


def _check_intent(question: dict[str, Any], result: dict[str, Any]) -> bool:
    expected_domains = set(_as_list(question.get("expected_intent_domains")))
    expected_channels = set(_as_list(question.get("expected_channels")))
    if not expected_domains and question.get("domain"):
        expected_domains = {str(question["domain"])}
    if not expected_channels and question.get("channel"):
        expected_channels = {str(question["channel"])}
    if not expected_domains and not expected_channels:
        return True

    intent = result.get("intent") or {}
    actual_domains = set(_as_list(intent.get("business_domains")))
    actual_channels = set(_as_list(intent.get("retrieval_channels")))
    return expected_domains.issubset(actual_domains) and expected_channels.issubset(
        actual_channels
    )


def _check_low_confidence_block(result: dict[str, Any]) -> bool:
    status = str(result.get("status", "")).lower()
    intent = result.get("intent") or {}
    if status in {"needs_clarification", "clarification", "blocked"}:
        return not _retrieval_results(result)
    if bool(intent.get("needs_clarification")):
        return not _retrieval_results(result)
    confidence = intent.get("confidence")
    return (
        isinstance(confidence, int | float)
        and confidence < 0.78
        and not _retrieval_results(result)
    )


def _check_plan(question: dict[str, Any], result: dict[str, Any]) -> bool:
    expected = question.get("expected_plan") or {}
    plan = result.get("retrieval_plan") or {}
    sub_queries = _sub_queries(plan)
    if not sub_queries:
        return not expected

    if len(sub_queries) < int(expected.get("min_sub_queries", 1)):
        return False
    domains = {str(sub_query.get("domain")) for sub_query in sub_queries}
    channels = {str(sub_query.get("channel")) for sub_query in sub_queries}
    profiles = {
        str((sub_query.get("structured_plan") or {}).get("query_profile"))
        for sub_query in sub_queries
        if sub_query.get("structured_plan")
    }
    if not set(_as_list(expected.get("required_domains"))).issubset(domains):
        return False
    if not set(_as_list(expected.get("required_channels"))).issubset(channels):
        return False
    if not set(_as_list(expected.get("required_structured_profiles"))).issubset(profiles):
        return False
    return True


def _check_unstructured_recall(question: dict[str, Any], result: dict[str, Any]) -> bool:
    expected_chunks = set(_as_list(question.get("expected_chunks")))
    if not expected_chunks:
        return True
    actual_chunks = _retrieved_chunk_ids(result)
    return expected_chunks.issubset(actual_chunks)


def _check_structured_correctness(question: dict[str, Any], result: dict[str, Any]) -> bool:
    expected_record_refs = set(_as_list(question.get("expected_record_refs")))
    expected_points = question.get("expected_aggregation_points") or []
    if not expected_record_refs and not expected_points:
        return True

    actual_record_refs = _retrieved_record_refs(result)
    if not expected_record_refs.issubset(actual_record_refs):
        return False
    return all(_has_aggregation_point(result, point) for point in expected_points)


def _check_sql_guardrail(result: dict[str, Any]) -> bool:
    for sub_query in _sub_queries(result.get("retrieval_plan") or {}):
        structured_plan = sub_query.get("structured_plan")
        if not structured_plan:
            continue
        if not isinstance(structured_plan, dict):
            return False
        if not _structured_plan_is_safe(structured_plan):
            return False
    return True


def _structured_plan_is_safe(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_SQL_KEYS:
                return False
            if str(key) == "limit" and isinstance(nested, int | float) and nested > 200:
                return False
            if not _structured_plan_is_safe(nested):
                return False
    elif isinstance(value, list):
        return all(_structured_plan_is_safe(item) for item in value)
    elif isinstance(value, str):
        lowered = value.lower()
        return not any(pattern in lowered for pattern in FORBIDDEN_SQL_PATTERNS)
    return True


def _check_citation_completeness(result: dict[str, Any]) -> bool:
    known_refs = _source_ref_ids(result)
    summary = result.get("llm_summary") or {}
    summary_refs = set(_as_list(summary.get("source_ref_ids")))
    content_refs = set(_extract_markdown_source_refs(str(summary.get("content") or "")))
    cited_refs = summary_refs | content_refs
    if cited_refs - known_refs:
        return False
    if known_refs and not cited_refs:
        return False
    return True


def _check_markdown_faithfulness(result: dict[str, Any]) -> bool:
    known_refs = _source_ref_ids(result)
    summary = result.get("llm_summary") or {}
    content = str(summary.get("content") or "")
    cited_refs = set(_as_list(summary.get("source_ref_ids"))) | set(
        _extract_markdown_source_refs(content)
    )
    if cited_refs - known_refs:
        return False
    if not known_refs and _looks_like_answer(content):
        return False
    return True


def _case_details(question: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_domain": question.get("domain"),
        "status": result.get("status"),
        "latency_ms": result.get("latency_ms"),
        "retrieved_chunks": sorted(_retrieved_chunk_ids(result)),
        "retrieved_record_refs": sorted(_retrieved_record_refs(result)),
        "source_ref_ids": sorted(_source_ref_ids(result)),
    }


def _aggregate_metrics(
    reports: list[CaseEvaluation],
    results: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = {
        "intent_accuracy": _check_rate(reports, "intent_accuracy"),
        "low_confidence_block_rate": _check_rate(reports, "low_confidence_block"),
        "plan_accuracy": _check_rate(reports, "plan_accuracy"),
        "unstructured_recall_at_k": _applicable_check_rate(
            reports, questions, "unstructured_recall_at_k", "expected_chunks"
        ),
        "structured_correctness": _structured_rate(reports, questions),
        "sql_guardrail_pass_rate": _check_rate(reports, "sql_guardrail"),
        "citation_completeness": _check_rate(reports, "citation_completeness"),
        "markdown_faithfulness_proxy": _check_rate(reports, "markdown_faithfulness_proxy"),
        "latency_ms": _latency_metrics(results),
        "ann_recall_at_k": _ann_recall(questions),
    }
    return metrics


def _threshold_failures(
    metrics: dict[str, Any],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    failures = []
    for metric, threshold in thresholds.items():
        value = metrics.get(metric)
        if value is None:
            continue
        if isinstance(value, int | float) and value < threshold:
            failures.append({"metric": metric, "value": value, "threshold": threshold})
    return failures


def _check_rate(reports: list[CaseEvaluation], check_name: str) -> float | None:
    applicable = [report for report in reports if check_name in report.checks]
    if not applicable:
        return None
    passed = sum(1 for report in applicable if report.checks[check_name])
    return _ratio(passed, len(applicable))


def _applicable_check_rate(
    reports: list[CaseEvaluation],
    questions: list[dict[str, Any]],
    check_name: str,
    expected_field: str,
) -> float | None:
    applicable = [
        report
        for report, question in zip(reports, questions, strict=True)
        if question.get(expected_field)
    ]
    if not applicable:
        return None
    passed = sum(1 for report in applicable if report.checks.get(check_name, False))
    return _ratio(passed, len(applicable))


def _structured_rate(
    reports: list[CaseEvaluation],
    questions: list[dict[str, Any]],
) -> float | None:
    applicable = [
        report
        for report, question in zip(reports, questions, strict=True)
        if question.get("expected_record_refs") or question.get("expected_aggregation_points")
    ]
    if not applicable:
        return None
    passed = sum(1 for report in applicable if report.checks.get("structured_correctness", False))
    return _ratio(passed, len(applicable))


def _latency_metrics(results: list[dict[str, Any]]) -> dict[str, float | None]:
    values = [
        float(result["latency_ms"])
        for result in results
        if isinstance(result.get("latency_ms"), int | float)
    ]
    if not values:
        return {"p50": None, "p95": None, "p99": None}
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
    }


def _ann_recall(questions: list[dict[str, Any]]) -> float | None:
    recalls = []
    for question in questions:
        exact = set(_as_list(question.get("exact_top_k")))
        ann = set(_as_list(question.get("ann_top_k")))
        if exact:
            recalls.append(_ratio(len(exact & ann), len(exact)))
    if not recalls:
        return None
    return round(sum(recalls) / len(recalls), 4)


def _percentile(values: list[float], percentile: int) -> float:
    if len(values) == 1:
        return round(values[0], 4)
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * (percentile / 100)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return round(sorted_values[lower], 4)
    fraction = index - lower
    interpolated = sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction
    return round(interpolated, 4)


def _result_question_id(result: dict[str, Any]) -> str:
    return str(result.get("question_id") or result.get("id") or "")


def _sub_queries(plan: dict[str, Any]) -> list[dict[str, Any]]:
    sub_queries = plan.get("sub_queries") if isinstance(plan, dict) else []
    if sub_queries is None:
        return []
    return [item for item in sub_queries if isinstance(item, dict)]


def _retrieval_results(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in result.get("retrieval_results") or [] if isinstance(item, dict)]


def _retrieved_chunk_ids(result: dict[str, Any]) -> set[str]:
    chunk_ids: set[str] = set()
    for retrieval_result in _retrieval_results(result):
        for item in retrieval_result.get("items") or []:
            if isinstance(item, dict) and item.get("chunk_id"):
                chunk_ids.add(str(item["chunk_id"]))
        for source_ref in retrieval_result.get("source_refs") or []:
            if isinstance(source_ref, dict) and source_ref.get("chunk_id"):
                chunk_ids.add(str(source_ref["chunk_id"]))
    return chunk_ids


def _retrieved_record_refs(result: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for retrieval_result in _retrieval_results(result):
        for source_ref in retrieval_result.get("source_refs") or []:
            if isinstance(source_ref, dict) and source_ref.get("record_ref"):
                refs.add(str(source_ref["record_ref"]))
    return refs


def _source_ref_ids(result: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for source_ref in result.get("source_refs") or []:
        if isinstance(source_ref, dict) and source_ref.get("source_ref_id"):
            refs.add(str(source_ref["source_ref_id"]))
    for retrieval_result in _retrieval_results(result):
        for source_ref in retrieval_result.get("source_refs") or []:
            if isinstance(source_ref, dict) and source_ref.get("source_ref_id"):
                refs.add(str(source_ref["source_ref_id"]))
    return refs


def _has_aggregation_point(result: dict[str, Any], point: dict[str, Any]) -> bool:
    group_field = point.get("group_field")
    group_value = point.get("group_value")
    metric = point.get("metric")
    expected_value = point.get("value")
    for retrieval_result in _retrieval_results(result):
        for aggregation in retrieval_result.get("aggregations") or []:
            if not isinstance(aggregation, dict):
                continue
            if metric is not None and aggregation.get("metric") != metric:
                continue
            for series_point in aggregation.get("series") or []:
                if not isinstance(series_point, dict):
                    continue
                if group_field and series_point.get(group_field) != group_value:
                    continue
                if expected_value is not None and series_point.get("value") != expected_value:
                    continue
                return True
    return False


def _extract_markdown_source_refs(content: str) -> list[str]:
    return re.findall(r"\[([A-Za-z0-9_.:-]+-src-[A-Za-z0-9_.:-]+)\]", content)


def _looks_like_answer(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    no_evidence_markers = ("无可用证据", "没有检索到", "未检索到", "no evidence")
    if any(marker in stripped.lower() for marker in no_evidence_markers):
        return False
    return len(stripped) >= 20 or stripped.startswith(("#", "-", "*"))


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def parse_thresholds(raw: list[str]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"threshold must be metric=value, got {item!r}")
        key, value = item.split("=", 1)
        thresholds[key.strip()] = float(value)
    return thresholds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        help="Override metric threshold, e.g. intent_accuracy=0.9",
    )
    args = parser.parse_args(argv)

    report = evaluate(
        load_jsonl(args.questions),
        load_jsonl(args.results),
        thresholds=parse_thresholds(args.threshold),
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 1 if report["summary"]["threshold_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
