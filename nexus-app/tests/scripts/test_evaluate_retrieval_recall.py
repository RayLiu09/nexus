from __future__ import annotations

import json

from scripts.evaluate_retrieval_recall import evaluate, load_jsonl, main


def _question(case_id: str = "ct-001") -> dict:
    return {
        "id": case_id,
        "domain": "course_textbook",
        "channel": "unstructured",
        "expected_intent_domains": ["course_textbook"],
        "expected_channels": ["unstructured"],
        "expected_plan": {
            "min_sub_queries": 1,
            "required_domains": ["course_textbook"],
            "required_channels": ["unstructured"],
        },
        "expected_chunks": ["chunk-1"],
    }


def _result(case_id: str = "ct-001") -> dict:
    return {
        "question_id": case_id,
        "status": "completed",
        "latency_ms": 120.0,
        "intent": {
            "business_domains": ["course_textbook"],
            "retrieval_channels": ["unstructured"],
            "confidence": 0.92,
        },
        "retrieval_plan": {
            "sub_queries": [
                {
                    "query_id": "q1",
                    "channel": "unstructured",
                    "domain": "course_textbook",
                    "unstructured_plan": {"top_k": 5},
                }
            ]
        },
        "retrieval_results": [
            {
                "query_id": "q1",
                "channel": "unstructured",
                "domain": "course_textbook",
                "items": [{"chunk_id": "chunk-1", "score": 0.91}],
                "source_refs": [
                    {
                        "source_ref_id": "q1-src-1",
                        "chunk_id": "chunk-1",
                    }
                ],
            }
        ],
        "llm_summary": {
            "content": "- 直播电商依托直播场景完成商品讲解和交易转化。[q1-src-1]",
            "source_ref_ids": ["q1-src-1"],
        },
    }


def test_evaluate_reports_passed_case():
    report = evaluate([_question()], [_result()])

    assert report["summary"]["passed_cases"] == 1
    assert report["summary"]["failed_cases"] == 0
    assert report["metrics"]["intent_accuracy"] == 1.0
    assert report["metrics"]["unstructured_recall_at_k"] == 1.0
    assert report["metrics"]["citation_completeness"] == 1.0
    assert report["metrics"]["latency_ms"]["p50"] == 120.0


def test_evaluate_fails_closed_for_missing_result():
    report = evaluate([_question("missing")], [])

    assert report["summary"]["failed_cases"] == 1
    assert report["failures"][0]["case_id"] == "missing"
    assert "run_result_present" in report["failures"][0]["checks"]


def test_evaluate_flags_raw_sql_and_unknown_citation():
    question = {
        "id": "md-001",
        "domain": "major_distribution",
        "channel": "structured",
        "expected_intent_domains": ["major_distribution"],
        "expected_channels": ["structured"],
        "expected_plan": {
            "required_domains": ["major_distribution"],
            "required_channels": ["structured"],
            "required_structured_profiles": ["major_distribution.trend_by_year"],
        },
    }
    result = {
        "question_id": "md-001",
        "status": "completed",
        "intent": {
            "business_domains": ["major_distribution"],
            "retrieval_channels": ["structured"],
            "confidence": 0.91,
        },
        "retrieval_plan": {
            "sub_queries": [
                {
                    "query_id": "q1",
                    "channel": "structured",
                    "domain": "major_distribution",
                    "structured_plan": {
                        "table_profile": "major_distribution.v1",
                        "query_profile": "major_distribution.trend_by_year",
                        "raw_sql": "select * from major_distribution_record",
                    },
                }
            ]
        },
        "retrieval_results": [
            {
                "source_refs": [
                    {"source_ref_id": "q1-src-1", "record_ref": "major_distribution_record:r1"}
                ]
            }
        ],
        "llm_summary": {
            "content": "- 趋势结论。[q1-src-1][q9-src-9]",
            "source_ref_ids": ["q1-src-1", "q9-src-9"],
        },
    }

    report = evaluate([question], [result])

    failed_checks = set(report["failures"][0]["checks"])
    assert "sql_guardrail" in failed_checks
    assert "citation_completeness" in failed_checks
    assert "markdown_faithfulness_proxy" in failed_checks


def test_evaluate_low_confidence_clarification_blocks_retrieval():
    question = {
        "id": "lc-001",
        "expect_clarification": True,
        "expected_intent_domains": [],
        "expected_channels": [],
    }
    result = {
        "question_id": "lc-001",
        "status": "needs_clarification",
        "intent": {
            "business_domains": ["course_textbook"],
            "retrieval_channels": ["unstructured"],
            "confidence": 0.42,
            "needs_clarification": True,
        },
        "retrieval_results": [],
        "llm_summary": {"content": "", "source_ref_ids": []},
    }

    report = evaluate([question], [result])

    assert report["cases"][0]["checks"]["low_confidence_block"] is True
    assert report["summary"]["passed_cases"] == 1


def test_load_jsonl_and_cli_write_report(tmp_path):
    questions = tmp_path / "questions.jsonl"
    results = tmp_path / "results.jsonl"
    output = tmp_path / "report.json"
    questions.write_text(json.dumps(_question(), ensure_ascii=False) + "\n", encoding="utf-8")
    results.write_text(json.dumps(_result(), ensure_ascii=False) + "\n", encoding="utf-8")

    assert load_jsonl(questions)[0]["id"] == "ct-001"
    exit_code = main([
        "--questions",
        str(questions),
        "--results",
        str(results),
        "--output",
        str(output),
    ])

    assert exit_code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["passed_cases"] == 1
