# Task Package: Retrieval Recall v1.0 Implementation Plan

## Source Context

- `AGENTS.md`: follow NEXUS architecture boundaries; no self-developed `llm-gateway`; use LiteLLM for model calls.
- `ARCHITECT.md`: semantic retrieval backend is adapter-based; pgvector is the P0 default adapter projection, not the domain model.
- `SPEC.md`: search/QA must remain traceable to normalized refs, chunks, source locators, and audit records.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: v1.0 retrieval uses four layers: intent recognition, query transformation, parallel retrieval, Markdown summary.
- Current implementation baseline: PGV-01 through PGV-04 have completed pgvector storage, indexing, search, and QA runtime.

## Goal

Create a concrete engineering implementation plan for the v1.0 retrieval/recall technical design so follow-up work can proceed through small reviewable slices.

## Scope

- Document current completed pgvector baseline.
- Define the target backend modules, internal APIs, and Console integration shape.
- Split implementation into bounded ORC-xx slices.
- Define each slice's goal, files, behavior, acceptance criteria, and risk boundaries.
- Call out prerequisites and remaining blockers before implementation starts.

## Out Of Scope

- Code implementation.
- Database migrations.
- API implementation.
- Console implementation.
- Prompt profile seeding.
- Retrieval quality benchmark execution.

## Forbidden Changes

- Do not reintroduce RAGFlow as the semantic retrieval or QA execution baseline.
- Do not use Evidence Graph as a retrieval/recall data source.
- Do not introduce a self-developed LLM gateway.
- Do not route Pipeline B structured assets through vector retrieval by default.
- Do not allow arbitrary LLM-generated SQL execution.
- Do not persist query plaintext, answer plaintext, source content, API keys, or Prompt plaintext into audit logs.

## Deliverables

- `docs/retrieval_recall_v1_implementation_plan.md`
- `docs/task-packages/wk_retrieval_recall_v1_implementation_plan_task_package.md`

## Acceptance

- The plan is based on the completed pgvector indexing/search/QA baseline.
- The plan defines implementable slices for schema, intent recognition, retrieval planning, unstructured retrieval, structured SQL retrieval, orchestration, Markdown summary, internal API, Console UI, structured-domain expansion, and evaluation.
- The plan states that v1.0 defaults to `access_scope = all_assets`.
- The plan preserves LiteLLM, pgvector adapter, source citation, audit, and no-RAGFlow/no-Evidence-Graph boundaries.
- The plan identifies remaining prerequisites before coding starts.

