# Task Package: Console RAG Chunk Semantic Context View

## Task name

Add a console-only semantic hierarchy view for RAG knowledge chunks.

## Source context

- `ARCHITECT.md`: `knowledge_chunk` is owned by NEXUS, links to
  `normalized_asset_ref`, and carries source locators for citation and audit.
- `SPEC.md`: Console asset detail exposes chunks and source traceability; search
  and QA must remain permission-filtered and citation-backed.
- `WORKFLOWS.md`: API contract and frontend UX changes require bounded scope
  and review evidence.
- `docs/evidence_graph_contextual_unit_design.md`: Evidence Graph
  `chunk_context_links` are diagnostic only and are not consumed by search/QA
  runtime yet.

## Goal

Let console operators inspect a hit RAG chunk together with its chapter,
section, and knowledge-point hierarchy from the existing chunk preview drawer,
without changing external search or QA APIs.

## Scope

- Add a console-internal chunk semantic hierarchy assembler.
- Add `GET /internal/v1/knowledge-chunks/{chunk_id}/semantic-context`.
- Add a Next.js proxy route under `/api/knowledge-chunks/{chunkId}/semantic-context`.
- Extend shared console chunk types.
- Extend `ChunkPreviewDrawer` with two views:
  - original source location
  - semantic hierarchy context
- Focused tests for backend context assembly and internal endpoint.

## Out of scope

- `/open/v1/search` changes.
- `/open/v1/qa` changes.
- RAGFlow adapter changes.
- Evidence Graph runtime context expansion.
- Cross-document canonical entity expansion.
- New persistent section tree or graph context tables.

## Forbidden changes

- Do not expose console-only semantic context through external `/open/v1/search`
  or `/open/v1/qa`.
- Do not consume raw files, raw JSON, or MinerU raw output as governance input.
- Do not add reverse pointers to `asset`, `asset_version`, `normalized_asset_ref`,
  or `knowledge_chunk`.
- Do not add a NEXUS AI gateway management page.
- Do not make RabbitMQ, Celery, Redis, or a new graph runtime required.

## Deliverables

- Backend semantic context helper with chapter / section / knowledge-point
  hierarchy and current-chunk range marking.
- Internal console API response envelope.
- Console proxy route and TypeScript types.
- Drawer UI with loading, error, empty, and populated states for semantic
  context.
- Test evidence.

## Acceptance

- Existing chunk preview behavior remains available as the default view.
- Semantic context view can show:
  - current chunk
  - current chunk's chapter / section / knowledge-point path
  - current chunk's parent section node
  - all knowledge points under that parent section
  - which knowledge-point range contains the current chunk
- `/open/v1/search` and `/open/v1/qa` files and contracts are untouched.
- Backend tests pass for the focused context path.

## Verification

```bash
cd nexus-api
uv run pytest tests/test_internal_chunk_preview.py
```
