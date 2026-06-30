# Pipeline A Major Profile Task Package

- **Status**: implementation in progress
- **Date**: 2026-06-30
- **Source context**:
  - `AGENTS.md`: Pipeline A document assets must use `ingest_validate -> assetize -> parse -> normalize`; PDF uses MinerU with auto model version and OCR auto-enabled; governance input must be `normalized_document` via `normalized_asset_ref`.
  - `docs/pipeline_a_major_profile_structured_data_design.md`: reviewed design for `major_profile.v1` domain tables and section-level semantic chunks.
  - `ARCHITECT.md` / `SPEC.md`: `knowledge_chunk.normalized_ref_id` links chunks to `normalized_asset_ref`; do not add reverse pointers.

## Goal

Implement Pipeline A support for professional introduction/profile documents (`major_profile`) with domain structured storage and section-level semantic chunks.

## Scope

- `nexus-app` domain models, Alembic migration, extractor, writer, and focused tests.
- `nexus-app` knowledge chunk strategy for `major_profile_knowledge` section chunks.
- Pipeline stage wiring that derives `major_profile` from `normalized_document` / `normalized_asset_ref`.
- Backend behavior only; keep external RAG index submission deferred.

## Out Of Scope

- New RAG backend selection or external index adapter implementation.
- Reintroducing RAGFlow as a target index backend for this feature.
- Console custom detail page implementation.
- Bulk/manual editing UI for `major_profile`.
- Full LLM extraction implementation beyond schema-ready deterministic/rule fallback needed for current samples/tests.

## Forbidden Changes

- Do not use `program` / `program_profile` naming.
- Do not bypass `normalized_document` or generate governance/domain data from raw PDF or MinerU raw JSON.
- Do not add `asset.current_version_id`, `asset_version.normalized_ref_id`, or reverse pointers from versions to normalized refs.
- Do not split semantic chunks by individual ability/course/certificate items; chunks are section-level semantic blocks.
- Do not make RAGFlow indexing a success requirement for `major_profile`.

## Deliverables

- `major_profile` domain tables and idempotent writer.
- `major_profile.v1` deterministic extractor for reviewed section fields.
- Section-level `major_profile_knowledge` chunks:
  - occupation section
  - training goal section
  - ability section
  - course/training section
  - certificate section
  - continuation section
- Focused tests for extractor, writer, and section chunking.

## Acceptance

- A normalized professional profile document can produce `major_profile*` domain rows.
- Ability/course/certificate lists are stored as structured domain rows.
- `knowledge_chunk` generation creates one chunk per major profile section, not one chunk per bullet/item.
- Chunks carry `normalized_ref_id`, `source_block_ids`, `locator`, `section_key`, and `section_title`.
- No RAGFlow call is required or introduced for this feature.

