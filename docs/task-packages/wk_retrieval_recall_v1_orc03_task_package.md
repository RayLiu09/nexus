# Task Package: ORC-03 Retrieval Plan Generation

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-03 generates executable `retrieval_plan` objects after high-confidence intent recognition.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: query transformation turns user questions into one or more structured/unstructured sub queries and exposes the plan to Console as auxiliary analysis.
- `nexus_app.retrieval.schemas`: ORC-01 contracts for `RetrievalPlan`, `RetrievalSubQuery`, `StructuredPlan`, and `UnstructuredPlan`.
- `nexus_app.retrieval.intent`: ORC-02 provides validated `RetrievalIntent`.

## Goal

Implement LLM-backed retrieval plan generation with schema validation, max sub-query limits, and safe failure behavior.

## Scope

- Add retrieval plan prompt construction.
- Add `RetrievalPlannerService`.
- Parse and validate LLM JSON into `RetrievalPlan`.
- Return a user-visible `query_transformation` conversation step.
- Reject schema-invalid plan output, including extra fields such as raw SQL.
- Add focused tests using fake LLM clients.

## Out Of Scope

- Executing the plan.
- pgvector retrieval executor.
- structured SQL executor.
- Orchestrator wiring.
- API and Console integration.
- Prompt profile persistence or seeding.

## Forbidden Changes

- Do not execute retrieval or SQL from the planner.
- Do not allow arbitrary LLM-generated SQL.
- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not persist query plaintext, plan text, model output text, Prompt text, source content, or API keys into audit logs.
- Do not increase `MAX_SUB_QUERIES` beyond the v1.0 default of 5.

## Deliverables

- `nexus-app/nexus_app/retrieval/planner.py`
- Prompt builder update in `nexus-app/nexus_app/retrieval/prompts.py`
- Settings additions for retrieval planner model alias and max sub-query count.
- `nexus-app/tests/retrieval/test_retrieval_planner.py`

## Acceptance

- Single unstructured fake LLM output returns a valid plan and completed `query_transformation` step.
- `major_distribution` fake LLM output returns a structured plan with query profile and no SQL text.
- Hybrid fake LLM output returns at least two sub queries and merge goal.
- Output with more than 5 sub queries fails safely.
- Output with undeclared `raw_sql` fails safely.
- Tests perform no network calls.

