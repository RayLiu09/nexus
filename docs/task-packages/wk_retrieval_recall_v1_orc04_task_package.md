# Task Package: ORC-04 Unstructured Retrieval Executor

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-04 executes `unstructured` sub queries through the pgvector search adapter.
- `nexus_app.index.pgvector_search`: existing pgvector-backed semantic search adapter.
- `nexus_app.retrieval.schemas`: ORC-01 contracts for `RetrievalSubQuery`, `RetrievalResult`, `UnstructuredResultItem`, and `RetrievalSourceRef`.

## Goal

Add a v1.0 retrieval executor for unstructured sub queries that normalizes pgvector search hits into the unified retrieval result schema.

## Scope

- Add `nexus_app.retrieval.executors` package.
- Add `UnstructuredRetrievalExecutor`.
- Reuse `PgvectorSearchAdapter`; do not implement new vector search logic.
- Map pgvector hits into `RetrievalResult.items` and `RetrievalResult.source_refs`.
- Add focused tests using fake search adapter.

## Out Of Scope

- Orchestrator integration.
- API integration.
- Console integration.
- Structured SQL retrieval.
- Rerank or hybrid keyword retrieval.
- Source citation enrichment through API-layer database joins.

## Forbidden Changes

- Do not call embedding providers directly.
- Do not reimplement pgvector similarity search.
- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not execute structured SQL.
- Do not persist query text, source content, or answer text.

## Deliverables

- `nexus-app/nexus_app/retrieval/executors/__init__.py`
- `nexus-app/nexus_app/retrieval/executors/unstructured.py`
- `nexus-app/tests/retrieval/test_unstructured_executor.py`

## Acceptance

- Fake pgvector adapter hits produce a completed `RetrievalResult`.
- Empty hits produce a completed result with empty `items` and `source_refs`.
- Executor passes `query_text`, `top_k`, `similarity_threshold`, and domain-derived `knowledge_type_code` to the search adapter.
- Each normalized item/source ref preserves chunk id, normalized ref id, score, content preview, metadata, locator, and collection/knowledge type metadata where present.

