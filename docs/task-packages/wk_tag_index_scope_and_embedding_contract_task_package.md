# Task Package: Tag Index Scope And Embedding Contract

## Source Context

- `AGENTS.md`: governance tags target normalized assets; retrieval changes need focused tests and contract updates.
- `ARCHITECT.md`: the Open asset catalog queries governed document tags on `normalized_asset_ref`; Task Outline retrieval filters chapter knowledge through `outline_node`.
- User decision (2026-07-30): retain tag indexes for document normalized refs and outline nodes; stop indexing Pipeline B structured records; tag vectors must use `TAG_EMBEDDING_MODEL` and its configured dimension.

## Goal

Make `tag_asset_index` a document and outline tag-retrieval projection, rather
than a generic structured-record semantic filter, and make the tag embedding
model/dimension explicit and non-fallback.

## Scope

- Retain governance-tag projection for `normalized_type=document` refs and outline-node projections.
- Stop Pipeline B field projections for job demand, major distribution, and occupational ability records.
- Reject structured-domain `tag_filters` through the query-profile contract.
- Delete existing rows for the four retired structured `target_type` values in an Alembic data migration.
- Add `TAG_EMBEDDING_DIMENSION` (default `512`) and require tag embedding callers/backfill to use `TAG_EMBEDDING_MODEL`.
- Update focused tests and root architecture/spec/readme documentation.

## Out Of Scope

- Changing governed tag output stored in AI governance results.
- Changing Open asset catalog request/response schemas.
- Deleting document/outline tag rows or changing chunk embeddings.
- Adding a new retrieval backend or asynchronous job system.

## Forbidden Changes

- Do not introduce enterprise IAM, a self-developed LLM gateway, or a new AI-governance service.
- Do not bypass normalized assets as governance inputs.
- Do not use the generic document embedding model as a fallback for tag vectors.

## Deliverables

- Scope-gated write and retrieval code.
- One data-cleanup Alembic migration.
- Configuration and backfill contract updates.
- Focused regression tests and root contract documentation.

## Acceptance

- New structured record writes create no `tag_asset_index` rows.
- Existing structured index rows are removed by migration; document and outline rows are untouched.
- Document governance tags and outline tags remain resolvable.
- Every tag-vector request uses `TAG_EMBEDDING_MODEL` and `TAG_EMBEDDING_DIMENSION`.
- Relevant unit/API tests pass.
