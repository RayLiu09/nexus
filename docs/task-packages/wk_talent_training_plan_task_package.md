# Task Package: Talent Training Plan Domain Projection

## Source Context

- `AGENTS.md`: governance and all domain projections consume `normalized_document` through `normalized_asset_ref`; raw MinerU output is never a domain or governance input.
- `ARCHITECT.md` / `SPEC.md`: Pipeline A document assets may produce evidence-bound domain read models and knowledge projections.
- `docs/pipeline_a_major_profile_structured_data_design.md`: `major_profile.v1` remains the lightweight professional-introduction projection.

## Goal

Create `talent_training_plan.v1` for the high-value, structured facts in institution-specific professional talent-training-plan documents: professional identity, training goal/specification, career orientation, certificates, and curriculum/course objectives/content. The projection supports structured retrieval and supplies evidence-bound inputs for position-capability and course-knowledge graph projection.

Add a bounded, secondary RAG projection for text that is not adequately served
by exact structured retrieval: training goal/specification, evidenced
position-capability descriptions, plan-owned course objectives/content, and
unmodelled supplementary sections.  Structured retrieval and deterministic
course/position graph views remain the primary retrieval path.

## Scope

- Pipeline A extraction from `normalized_document.blocks` only.
- `talent_training_plan` main table plus `talent_training_plan_course` plan-owned course rows.
- `career_orientation`, `training_specification`, and `certificates` are controlled JSON attributes of the plan, not platform master data.
- Read-only internal/open APIs with structured filters.
- Deterministic heading/table extraction, evidence locators, idempotent writer, migration, focused tests, and read-only course/optional-position graph views.
- NEXUS-owned `talent_training_plan_decompose` semantic projection from the
  persisted `normalized_document` payload, with pgvector indexing through the
  existing `talent_training_dataset` knowledge type.

## Out Of Scope

- Industry, occupation, position, skill, or certificate master-data tables.
- Curriculum validation, credit-hour reconciliation, or compliance checks.
- Full teaching schedule, admission requirement, implementation assurance, graduation requirement data modeling.
- Vector copies of plan identity, simple course/position filters, or certificate
  attributes already covered by structured retrieval.
- New Console UI, manual editing, or changing `major_profile.v1` semantics.
- Evidence Graph (`knowledge_graph_*`) extraction or persistence for talent-training-plan assets.

## Forbidden Changes

- Do not read MinerU raw output directly in the extractor.
- Do not treat a plan-local occupation, position, skill, or certificate as global canonical master data.
- Do not make JSON the only durable representation of courses needed for structured retrieval and graph projection.
- Do not replace `major_profile.v1`; it remains a separate lightweight projection.
- Do not submit a talent-training-plan normalized ref to the generic Evidence Graph build queue.
- Do not use raw MinerU/PDF/image data for RAG chunks, or duplicate already
  modelled course/position table text as fallback document chunks.

## Deliverables

- Domain schema, SQLAlchemy models, Alembic migration, deterministic extractor/writer, Pipeline A integration, and read APIs.
- Tests for table/heading extraction, persistence idempotency, and API filters.
- Contract documentation and review evidence.
- Focused semantic-chunk tests and a dry-run-first historical re-chunk/re-index
  utility for existing talent-training-plan refs.

## Acceptance

- A normalized talent-training-plan document produces exactly one plan projection per normalized ref and plan-owned course rows.
- Career orientation / specification / certificates preserve source evidence in controlled JSON.
- Queries support institution, major name/code, duration, position, skill, certificate, and course filters.
- No global industry/occupation/position/skill/certificate rows are created.
- Every plan exposes a deterministic course knowledge graph view; a position-capability graph is exposed only when the plan contains evidenced position-to-skill facts.
- RAG chunks are emitted only for the bounded supplementary semantic units,
  preserve normalized block locators, and are idempotently indexed into the
  existing pgvector path under `talent_training_dataset`.
