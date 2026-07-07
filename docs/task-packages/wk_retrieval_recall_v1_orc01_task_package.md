# Task Package: ORC-01 Retrieval Schema And Domain Registry

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-01 defines the first implementation slice for v1.0 retrieval/recall orchestration.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: four-layer retrieval flow requires structured `intent`, `retrieval_plan`, `retrieval_results`, `context_pack`, and `conversation_steps`.
- `ARCHITECT.md`: semantic retrieval backend remains adapter-based; pgvector projection tables are not domain models.
- `SPEC.md`: search/QA must keep source traceability and audit hygiene.

## Goal

Add the pure schema and domain-registry foundation for v1.0 retrieval/recall orchestration without changing runtime search, QA, API, database, or Console behavior.

## Scope

- Add `nexus_app.retrieval` package.
- Add Pydantic v2 runtime/response schemas for:
  - retrieval intent
  - retrieval plan
  - sub queries
  - structured/unstructured result envelopes
  - source refs
  - context pack
  - conversation steps
- Add a static domain registry for first-batch domains and query profiles.
- Add focused tests for schema validation and registry lookup.

## Out Of Scope

- LLM intent recognition implementation.
- Query transformation implementation.
- pgvector executor implementation.
- structured SQL executor implementation.
- Orchestrator implementation.
- API and Console integration.
- Database migrations.

## Forbidden Changes

- Do not modify `/open/v1/search` or `/open/v1/qa`.
- Do not add persistence tables.
- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not permit arbitrary SQL or raw SQL fields in structured plans.
- Do not define audit schemas that require query plaintext, answer plaintext, Prompt plaintext, source content, or API keys.

## Deliverables

- `nexus-app/nexus_app/retrieval/__init__.py`
- `nexus-app/nexus_app/retrieval/schemas.py`
- `nexus-app/nexus_app/retrieval/domain_registry.py`
- `nexus-app/tests/retrieval/test_retrieval_schemas.py`
- `nexus-app/tests/retrieval/test_domain_registry.py`

## Acceptance

- Schemas validate high-confidence and low-confidence intent payloads.
- Schemas validate hybrid retrieval plans with structured and unstructured sub queries.
- Structured plans reject undeclared fields such as `raw_sql`.
- Context packs default to `access_scope = all_assets`.
- Registry resolves default channel, executor key, and query profiles for:
  - `course_textbook`
  - `major_profile`
  - `major_distribution`
  - `job_demand`
  - `competency_analysis`
- Tests run without network calls or database setup.

