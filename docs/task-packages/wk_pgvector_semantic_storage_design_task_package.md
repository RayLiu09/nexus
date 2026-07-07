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
