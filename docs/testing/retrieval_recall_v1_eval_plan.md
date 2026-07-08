# NEXUS v1.0 Retrieval/Recall Evaluation Plan

- **Status**: v1.0 baseline
- **Related implementation plan**: `docs/retrieval_recall_v1_implementation_plan.md`
- **Execution mode**: offline first. The evaluator consumes exported JSONL from retrieval/recall runs; a live API runner can be added later.

## 1. Purpose

ORC-11 establishes a measurable quality and safety baseline for the v1.0 four-layer retrieval/recall flow:

1. intent recognition
2. query transformation / retrieval plan generation
3. parallel retrieval
4. Markdown summary generation

This is not a new retrieval implementation. It is an acceptance and regression framework for the current pgvector-backed unstructured retrieval and guarded SQL structured retrieval path.

## 2. Evaluation Inputs

The evaluator uses two JSONL files.

### 2.1 Question Specs

Each line is one expected case:

```json
{
  "id": "ct-001",
  "domain": "course_textbook",
  "channel": "unstructured",
  "query": "什么是直播电商？请结合教材内容解释。",
  "expect_clarification": false,
  "expected_intent_domains": ["course_textbook"],
  "expected_channels": ["unstructured"],
  "expected_plan": {
    "min_sub_queries": 1,
    "required_domains": ["course_textbook"],
    "required_channels": ["unstructured"]
  },
  "expected_chunks": ["chunk-live-commerce-definition"],
  "expected_source_refs": ["chunk:chunk-live-commerce-definition"]
}
```

Structured cases may also include:

```json
{
  "expected_plan": {
    "required_structured_profiles": ["job_demand.count_by_city"]
  },
  "expected_record_refs": ["job_demand_record:record-shanghai-001"],
  "expected_aggregation_points": [
    {"group_field": "city", "group_value": "上海", "metric": "sum(job_count)", "value": 12}
  ]
}
```

Optional ANN comparison cases may include:

```json
{
  "exact_top_k": ["chunk-a", "chunk-b", "chunk-c"],
  "ann_top_k": ["chunk-a", "chunk-c", "chunk-d"]
}
```

### 2.2 Run Outputs

Each line is one exported retrieval run:

```json
{
  "question_id": "ct-001",
  "status": "completed",
  "latency_ms": 820.5,
  "intent": {
    "business_domains": ["course_textbook"],
    "retrieval_channels": ["unstructured"],
    "confidence": 0.91
  },
  "retrieval_plan": {
    "sub_queries": [
      {
        "query_id": "q1",
        "channel": "unstructured",
        "domain": "course_textbook",
        "unstructured_plan": {"top_k": 5}
      }
    ]
  },
  "retrieval_results": [
    {
      "query_id": "q1",
      "channel": "unstructured",
      "domain": "course_textbook",
      "items": [
        {"chunk_id": "chunk-live-commerce-definition", "score": 0.88}
      ],
      "source_refs": [
        {"source_ref_id": "q1-src-1", "chunk_id": "chunk-live-commerce-definition"}
      ]
    }
  ],
  "llm_summary": {
    "content": "- 直播电商是通过直播完成商品讲解和交易转化。[q1-src-1]",
    "source_ref_ids": ["q1-src-1"]
  }
}
```

The run exporter must not store API keys, raw prompt text, large source content, or L3/L4 plaintext.

## 3. Metrics

| Metric | Definition | v1.0 Gate |
| --- | --- | --- |
| Intent accuracy | Expected domains and channels are included in actual intent. | >= 0.80 pilot baseline |
| Low-confidence blocking accuracy | Cases marked `expect_clarification=true` stop before retrieval. | 1.00 for curated negative set |
| Plan accuracy | Required sub-query count, domains, channels, and structured profiles are present. | >= 0.80 |
| Unstructured recall@K | Expected chunk ids found in retrieval items/source refs. | >= 0.60 integration, >= 0.80 pilot target |
| Structured correctness | Expected record refs and aggregation points are returned. | >= 0.90 for deterministic SQL fixtures |
| SQL guardrail pass rate | No raw SQL fields, forbidden SQL text, or limit overrun in structured plans. | 1.00 |
| Citation completeness | Summary cites only known source refs and cites at least one retrieved source when evidence exists. | >= 0.95 |
| Markdown faithfulness proxy | No unknown source refs; no answer-like Markdown when there is no evidence. | >= 0.95 |
| Latency P50/P95/P99 | Measured from run output `latency_ms`. | reported, not hard-gated in ORC-11 |
| ANN recall@K | Optional overlap of ANN top-k against exact top-k. | reported when supplied |

The evaluator is intentionally conservative. Unknown citations, forbidden raw SQL fields, missing run results, and configured threshold violations are failures.

## 4. Safety Checks

Structured retrieval safety is evaluated on the emitted retrieval plan:

- `structured_plan.sql`, `structured_plan.raw_sql`, `structured_plan.statement`, `structured_plan.query`, and `structured_plan.text_sql` are forbidden.
- String values containing `select `, `insert `, `update `, `delete `, `drop `, `alter `, `;`, `--`, or `/*` inside structured plans are flagged.
- `limit` must be `<= 200`.
- Structured cases must use registered query profile keys in the question spec expectations.

This does not replace runtime `sql_guardrails.py`; it verifies that exported plans preserve the same fail-closed posture.

## 5. Reporting

The evaluator emits JSON:

```json
{
  "summary": {
    "total_cases": 25,
    "passed_cases": 22,
    "failed_cases": 3,
    "overall_pass_rate": 0.88
  },
  "metrics": {
    "intent_accuracy": 0.92,
    "sql_guardrail_pass_rate": 1.0,
    "latency_ms": {"p50": 820.5, "p95": 1410.2, "p99": 1602.4}
  },
  "failures": [
    {"case_id": "jd-003", "checks": ["structured_correctness"]}
  ]
}
```

The JSON report is suitable for CI artifact storage. A Markdown renderer can be added later, but ORC-11 keeps the first slice machine-readable.

## 6. Initial Execution Steps

1. Export run outputs for the cases in `docs/testing/retrieval_recall_v1_question_set.md` into a JSONL file.
2. Convert or maintain the selected question specs as JSONL.
3. Run:

```bash
cd nexus-app
uv run python scripts/evaluate_retrieval_recall.py \
  --questions ../tmp/retrieval_questions.jsonl \
  --results ../tmp/retrieval_runs.jsonl \
  --output ../tmp/retrieval_eval_report.json
```

4. Review failed cases and decide whether the fix belongs to prompt tuning, data indexing, SQL profile registration, source-ref enrichment, or summary grounding.

## 7. Known Limitations

- Markdown faithfulness is a deterministic proxy in ORC-11. It checks source-ref grounding shape, not semantic entailment.
- ANN recall comparison is optional until exact-baseline exports are available.
- Permission filtering is not evaluated because v1.0 retrieval conversation defaults to `access_scope = all_assets`.
- The evaluator does not call LiteLLM, pgvector, or PostgreSQL; it evaluates exported outputs only.
