# Task Package: pgvector Semantic Storage Design

## Source Context

- `AGENTS.md`: semantic retrieval must preserve NEXUS adapter boundaries; raw files, raw JSON, and MinerU raw output are not valid governance inputs.
- `ARCHITECT.md`: Knowledge Pipeline is independent and connected through `normalized_asset_ref`; semantic retrieval backend internals must not own NEXUS master data, permissions, governance, or audit authority.
- `SPEC.md`: search/QA must be traceable to normalized refs, chunks, source locators, and audit records.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: retrieval orchestration uses intent recognition, query transformation, parallel retrieval, and Markdown summary; v1.0 defaults to all-assets access while reserving permission/governance filters.

## Goal

Document pgvector as the P0 default semantic vector storage and retrieval adapter for NEXUS Knowledge Pipeline 1 while preserving adapter replaceability, traceability, permission/governance filter reservation, and future scale-up paths.

## Scope

- Update retrieval enhancement design documentation.
- Update architecture, requirements, and README summary wording for the selected P0 default.
- Define pgvector table ownership, embedding metadata, index strategy, query flow, capacity risks, concurrency risks, multimodal limitation, and scale-up triggers.

## Out Of Scope

- Database migration implementation.
- Backend adapter code.
- Public `/v1` API contract freeze.
- Production capacity benchmark execution.
- Selecting a dedicated vector database for post-P0 scale-up.

## Forbidden Changes

- Do not make pgvector part of the domain model contract; it remains an adapter implementation detail.
- Do not make raw files, raw JSON, or MinerU output valid retrieval governance inputs.
- Do not route structured record assets through chunk/vector retrieval by default.
- Do not implement permission filtering in P0; only reserve filter fields and execution points.
- Do not remove source citation, `normalized_ref_id`, chunk locator, or audit requirements.

## Deliverables

- `docs/knowledge_retrieval_result_enhancement_v1.0.md`
- `ARCHITECT.md`
- `SPEC.md`
- `readme.md`

## Acceptance

- The design states that pgvector is the P0 default semantic vector storage adapter.
- The design preserves `knowledge_chunk` as the NEXUS-owned retrieval anchor and keeps embedding/index data as projection data.
- The design reserves permission and governance status filters while stating that P0 defaults to all-assets access.
- The design explicitly lists pgvector weaknesses: storage capacity growth, PostgreSQL concurrency pressure, filtered ANN recall risk, and lack of multimodal vector retrieval coverage.
- The design defines upgrade triggers for dedicated vector/retrieval engines.

## Implementation Slice: PGV-01 LiteLLM Embedding Config And Collector Storage

### Goal

Add the minimal pgvector storage foundation needed by the v1.0 retrieval plan without replacing `/v1/search` or `/v1/qa` yet.

### Scope

- Add embedding configuration loaded from `.env.dev`, with `DEFAULT_EMBEDDING_MODEL` as the default model alias and optional `LITELLM_EMBEDDING_MODEL_ALIAS` as the LiteLLM gateway override.
- Add pgvector-backed logical collector tables:
  - `vector_collection`: one logical collector per data asset domain type, normalized type, model alias, metric, and schema version.
  - `knowledge_embedding_pgvector`: embedding projection rows anchored by `knowledge_chunk`.
- Add a LiteLLM embedding client that calls the OpenAI-compatible `/v1/embeddings` endpoint and validates dimensions without logging input text or credentials.
- Add a collector resolver and metadata projection helper that derives `asset_domain_type`, `collection_key`, traceability fields, and future filter metadata from `NormalizedAssetRef` and `KnowledgeChunk`.
- Add focused tests for config loading, client behavior, collection resolution, metadata projection, and SQLite model compatibility.

### Out Of Scope

- Replacing existing `/open/v1/search` and `/open/v1/qa` runtime behavior.
- Implementing LLM intent recognition, query transformation, rerank, SQL structured retrieval, or Console multi-step interaction UI.
- Building the background index worker that batches chunks into embeddings.
- Permission filtering execution. Metadata/filter fields are reserved only.

### Forbidden Changes

- Do not call embedding providers directly; embedding calls must go through LiteLLM.
- Do not use RAGFlow as a semantic retrieval baseline.
- Do not add external backend ids or reverse pointers to `knowledge_chunk`.
- Do not make structured Pipeline B domain tables use vector retrieval by default.
- Do not log API keys, raw chunk text, prompt text, or large content.

### Acceptance

- `Settings()` loads `DEFAULT_EMBEDDING_MODEL` from `.env.dev`.
- `effective_embedding_model_alias` prefers `LITELLM_EMBEDDING_MODEL_ALIAS` when set.
- pgvector projection tables can be created by Alembic on PostgreSQL and by SQLAlchemy metadata in SQLite tests.
- The LiteLLM embedding client sends `{"model": alias, "input": texts}` to `{LITELLM_ENDPOINT}/v1/embeddings` and rejects dimension mismatches.
- Collection keys are separated by data asset domain type and include normalized type, model alias, and schema version.
- Metadata projection includes asset/ref/chunk traceability fields and future permission/governance filter fields.
