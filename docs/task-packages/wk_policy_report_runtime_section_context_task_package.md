# Task name

Policy/report runtime document section context for retrieval recall.

# Source context

- `ARCHITECT.md`: Query Router v2 may expand query evidence for `/open/v1/query` and `/internal/v1/query`; `/open/v1/search` remains compact chunk evidence.
- `SPEC.md`: Search and QA responses must retain normalized ref, chunk id, locator, source traceability, and bounded contexts.
- `WORKFLOWS.md`: Semantic Retrieval Integration Gate applies because the change affects retrieval expansion and QA citations.
- User-approved implementation plan:
  1. Implement runtime `DerivedDocumentSectionBuilder`.
  2. Apply section grouping + ranking to `industry_research_kb` hit results.
  3. Return bounded `document_section_context` in internal/open query.
  4. Build a golden query validation set for 5 report assets.
  5. Consider persisted `document_section` only after effect is proven.

# Goal

Improve policy/report and industry-report retrieval recall quality by expanding flat chunk hits into bounded, business-readable document section contexts at query time, without changing the underlying chunk model.

# Scope

- Retrieval runtime context assembly under `nexus-app/nexus_app/retrieval/`.
- Query Router v2 projection of section contexts.
- Composer handling for `document_section_context` evidence.
- Unit tests for grouping, ranking exposure, and deterministic rendering.
- Golden query validation documentation under `docs/`.
- Contract documentation updates in `ARCHITECT.md`, `SPEC.md`, and `readme.md`.

# Out of scope

- No database migration.
- No persisted `document_section` table.
- No `knowledge_chunk.document_section_id`.
- No in-process TTL cache.
- No change to `/open/v1/search`.
- No raw-file or MinerU raw-output inference.
- No LLM-generated ungrounded section inference.
- No frontend UI change.

# Forbidden changes

- Do not introduce enterprise IAM.
- Do not develop an `llm-gateway`.
- Do not create an independent AI governance service.
- Do not add reverse pointers to `asset`, `asset_version`, or `normalized_asset_ref`.
- Do not write section results to the database.
- Do not use raw files, raw JSON, or MinerU raw output as retrieval section input.

# Deliverables

- Runtime `document_section_context` construction from existing `knowledge_chunk` rows.
- Section grouping by contiguous `locator.heading_path` and chunk order.
- Section ranking from first-stage hit evidence, title/path relevance, and support count.
- Bounded context payload with `quality_flags`, `locator`, `source_block_ids`, chunk counts, and char counts.
- Query-intent gate so policy/report exact facts, locators, asset discovery,
  definitions, and comparisons do not return full document sections.
- Query result projection under existing `section_contexts`.
- Deterministic Composer rendering for `document_section_context`.
- Golden query validation doc for 5 policy/report assets.

# Acceptance

Focused tests:

```bash
uv run pytest \
  tests/retrieval/test_tool_executors_v2.py::test_search_chunks_builds_document_section_context_for_industry_report \
  tests/retrieval/test_tool_executors_v2.py::test_document_section_context_marks_partial_missing_heading_path \
  tests/retrieval/test_tool_executors_v2.py::test_search_chunks_scopes_compact_query_to_decorated_outline_title \
  tests/retrieval/test_composer_v2.py::test_document_section_context_renders_without_llm \
  tests/retrieval/test_composer_v2.py::test_section_context_restores_locator_subheadings_without_llm \
  tests/retrieval/test_router_v2.py::test_section_context_projection_includes_document_section_context
```

Key assertions:

- `industry_research_kb` hits can produce `kind=document_section_context`.
- `document_section_context` is returned only for section/topic summary,
  trends, stages, and policy-measure enumeration intents.
- Exact fact, existence/locator, asset discovery, definition, and comparison
  queries keep compact chunk evidence.
- Table-like or heading-less chunks remain under the nearest section and expose quality flags when partial.
- Existing textbook `section_context` behavior still renders.
- Router exposes the bounded document section context through `section_contexts`.
- Composer cites `normalized_ref_id`, `chunk_id`, and `locator`.
