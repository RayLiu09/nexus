# Task Package: Major Profile And Teaching Standard Knowledge Views

## Status

Implementation in progress (2026-07-14).

## Source Context

- `AGENTS.md`: knowledge processing is anchored on `normalized_asset_ref`; P0
  semantic retrieval uses pgvector and RAGFlow is not the active baseline.
- `ARCHITECT.md`: `knowledge_chunk.normalized_ref_id` is the evidence anchor;
  `index_manifest` owns index execution state; document assets remain on
  Pipeline A (`ingest_validate -> assetize -> parse -> normalize`).
- `SPEC.md`: asset detail views must retain source traceability and index
  failures must be recoverable.
- `WORKFLOWS.md`: this slice requires Data Model, API Contract, Semantic
  Retrieval Integration, and Frontend UX Review Gates before merge.

## Goal

Provide focused, selectable professional graphs for professional-introduction
assets, and give teaching-standard assets the same three asset-detail views
(`知识块`, `目录`, `专业图谱`) through an independent teaching-standard domain
projection. Enforce a single knowledge-processing emission per governed asset
classification and keep active indexing on NEXUS pgvector only.

## Frozen Contracts

1. Each admitted classification generates zero or one `knowledge_emissions`
   item. The item is always the configured `primary_knowledge_type`; conditional
   co-emission is removed from active inference.
2. Graph eligibility is a capability of that single knowledge type
   (`graph_profile` / strategy metadata), not a second emitted knowledge type.
3. `major_profile` remains the domain model for professional introductions.
   `teaching_standard` uses dedicated `teaching_standard_profile*` projection
   tables and extractor payloads. The two models may share view semantics but
   must not share a forced storage schema.
4. Teaching-standard graph vocabulary is:
   `专业 -> 职业领域 -> 典型工作任务 -> 课程 -> 知识与要求`.
   Course teaching content/requirements retain evidence locators and never
   become ungrounded graph nodes.
5. Console-only teaching-standard read APIs are internal Next.js route
   handlers backed by the existing `/v1` API adapter. No public API is added in
   this slice.
6. Active NEXUS chunks index only through pgvector. Historical RAGFlow code is
   not invoked by either major-profile or teaching-standard processing.

## Scope

- Professional graph selector, default-first selection, and removal of graph
  node/edge statistics.
- Single-emission deterministic inference and corresponding rules cleanup.
- Dedicated teaching-standard extractor, projection, section chunks, API
  serialization, and asset-detail three-view UI.
- Idempotent chunk/index continuation for existing admitted teaching-standard
  refs that have emissions but no chunks/manifests.
- Focused tests and contract documentation updates.

## Out Of Scope

- Deleting every historical RAGFlow compatibility module or migration.
- Public/open teaching-standard search APIs.
- Manual data repair by direct database inserts.
- New queue infrastructure, Celery, RabbitMQ, or a graph operations center.

## Forbidden Changes

- Do not read raw file, raw JSON, or MinerU output as governance, projection,
  chunk, or graph input.
- Do not add reverse pointers to `asset` or `asset_version`.
- Do not overload `MajorProfileCourse` with teaching-standard work tasks or
  course requirements.
- Do not render all professionals at once in either graph view.
- Do not reintroduce RAGFlow into an active indexing path.

## Deliverables

- Professional graph selector and no graph statistics component.
- Single emission inference plus graph metadata on the primary type.
- `teaching_standard_profile*` domain projection with evidence-bearing course
  content and requirements.
- Teaching-standard chunks, directory and per-professional graph view.
- Idempotent recovery/catch-up for the knowledge/index tail.
- Focused unit/integration tests and review evidence.

## Acceptance Evidence

```bash
cd nexus-app
uv run pytest tests/ai_governance/test_knowledge_emissions_e2e.py \
  tests/governance/test_pipeline_integration.py

cd ../nexus-api
uv run pytest

cd ../nexus-console
npm run typecheck
```

- A `major_profile` graph defaults to its first professional, offers a
  professional selector, renders only that professional, and contains no
  node/edge statistics.
- An admitted teaching standard creates dedicated structured rows, section
  chunks, and a pgvector index manifest idempotently.
- Teaching-standard detail provides the three named views and graphs only the
  selected professional.
- Every classification generates at most one emission and a graph-capable
  primary emission queues at most one matching graph build.
