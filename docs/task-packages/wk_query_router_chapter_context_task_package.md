# Task Package: Query Router Chapter Context Expansion

## Source Context

- `ARCHITECT.md`: NEXUS owns `knowledge_chunk`, its source locator, and the
  theory-textbook `knowledge_outline_node` relation.
- `SPEC.md`: `POST /open/v1/query` and `POST /internal/v1/query` are the P0
  Query Router v2 entry points. `GET /open/v1/search` remains a chunk-evidence
  API.
- Real development-data verification, 2026-07-30: a 50-chunk textbook
  section was returned as a single chunk by both Query Router v2 entry points.

## Goal

When a v2 semantic query hits theory-textbook chunks, return complete context
for at most the top three distinct matched outline sections without requiring
the caller to know an outline-node id.

## Scope

- Derive section candidates from the ranked hit chunks' `knowledge_outline_node_id`.
- Expand at most three distinct theory-textbook sections in document order.
- Surface the contexts in both `/open/v1/query` and `/internal/v1/query`.
- Render one or more complete selected sections deterministically in the v2
  Markdown answer.
- Preserve `/open/v1/search` and legacy `/internal/v1/knowledge-retrieval/*`
  behavior.

## Out Of Scope

- Generic policy/report section modelling.
- Caller-supplied `outline_node_id` for v2 query APIs.
- Changing the legacy retrieval-test Console workflow.
- Altering `/open/v1/search` or `/open/v1/qa` response schemas.

## Contract

- New v2 response field: `section_contexts: list`.
- A returned context includes its outline node, title, ordered chunks, total
  chunk count, total character count, and `complete=true`.
- At most three contexts are returned, deduplicated by outline node, in ranked
  first-hit order.
- Only `knowledge_outline_node` (theory textbook) contexts are expanded.

## Acceptance

- Unit tests prove ranked hit-node expansion, three-section cap, deduplication,
  ordered full content, and no expansion for unlinked chunks.
- API tests prove both v2 entry points expose the new field.
- Local E2E demonstrates a textbook chapter query returns the selected
  chapter's full chunk set through both v2 endpoints.
