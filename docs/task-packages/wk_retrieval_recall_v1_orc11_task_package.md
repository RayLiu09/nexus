# Task Package: ORC-11 Retrieval Recall Evaluation Baseline

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-11 establishes the v1.0 retrieval/recall quality and safety baseline.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: retrieval/recall results must preserve intent analysis, retrieval plans, source refs, and Markdown traceability.
- `nexus_app.retrieval`: v1.0 schemas, intent, planner, executors, orchestrator, and summary services.
- `WORKFLOWS.md`: non-trivial work needs a bounded task package and verification evidence.

## Goal

Create a repeatable offline evaluation baseline for v1.0 retrieval/recall so quality and safety can be measured before acceptance, rather than relying only on unit tests or manual demo checks.

## Scope

- Add an evaluation plan document.
- Add a first-pass business question set covering all v1.0 domains.
- Add a local JSONL evaluator script for exported retrieval/recall runs.
- Add tests for evaluator metric calculation and safety checks.

## Out Of Scope

- Live API runner against `/internal/v1/knowledge-retrieval/query`.
- Production benchmark data generation.
- Model tuning, prompt tuning, or reranker tuning.
- Permission filtering; v1.0 still defaults to `access_scope = all_assets`.
- New retrieval data sources.
- Knowledge Outline implementation.

## Forbidden Changes

- Do not modify retrieval runtime behavior.
- Do not add database migrations, model fields, or API contracts.
- Do not introduce raw SQL execution in evaluation fixtures.
- Do not require network calls or LiteLLM calls in tests.
- Do not include unrelated Knowledge Outline changes.

## Deliverables

- `docs/testing/retrieval_recall_v1_eval_plan.md`
- `docs/testing/retrieval_recall_v1_question_set.md`
- `nexus-app/scripts/evaluate_retrieval_recall.py`
- `nexus-app/tests/scripts/test_evaluate_retrieval_recall.py`

## Acceptance

- Evaluation plan defines metrics for intent, low-confidence blocking, plan quality, unstructured recall, structured correctness, SQL guardrails, Markdown faithfulness, citation completeness, latency, and optional ANN recall checks.
- Question set contains at least 5 questions for each v1.0 domain: `course_textbook`, `major_profile`, `major_distribution`, `job_demand`, and `competency_analysis`.
- Evaluator can consume JSONL question specs and JSONL run outputs, then emit machine-readable JSON metrics.
- Evaluator fails closed on missing run results, forbidden raw SQL fields, unknown citations, and configured threshold violations.
- Tests run offline with no network calls.
