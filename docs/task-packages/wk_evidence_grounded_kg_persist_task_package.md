# Task Package: Evidence-grounded KG Merge Quality Persist

## Source Context

- `docs/evidence_grounded_kg_implementation_plan.md`: Task Package D requires entity normalization, relation normalization, fact dedup, evidence binding, quality gate, and graph persistence.
- `nexus-app/nexus_app/evidence_graph/schemas.py`: Task Package C provides validated `GraphFactCandidate` intermediate objects.
- `nexus-app/nexus_app/models.py`: Task Package A provides the official `knowledge_graph_*` tables.

## Goal

Persist validated graph fact candidates into official Evidence-grounded KG tables only after build-scope normalization, deduplication, evidence binding, and quality checks.

## Scope

- `nexus-app/nexus_app/evidence_graph/persist.py`: merge, quality, and persistence service.
- `nexus-app/tests/`: tests for successful persistence, dedup, evidence binding, low-confidence handling, and missing-evidence blocking.
- `docs/evidence_grounded_kg_implementation_plan.md`: mark Task Package D as started.

## Out Of Scope

- Internal API endpoints.
- Console graph rendering.
- Advanced conflict resolution and human review workflow.
- Graph database backend.
- Productized profile-specific quality policy editor.

## Forbidden Changes

- Do not persist facts without evidence.
- Do not persist low-confidence candidates as official graph facts in this slice.
- Do not use raw files, raw JSON, or MinerU raw output as evidence sources.
- Do not change Pipeline B capability graph staging.

## Deliverables

- `persist_graph_candidates(...)` service.
- Conservative entity normalization:
  - trims whitespace.
  - maps `我国` / `国内` to `中国`.
- Conservative predicate normalization:
  - maps `同比增长` / `增长` / `增速为` to `HAS_GROWTH_RATE`.
  - maps `发布` / `印发` / `出台` to `ISSUED_BY`.
- Fact dedup keyed by subject, predicate, object/literal, qualifiers, and fact type.
- Evidence binding to `knowledge_chunk.id`, `source_block_ids`, `locator`, and `evidence_text`.
- Build counters and `quality_summary` update.

## Acceptance

- Formal graph rows are written only when evidence exists.
- Duplicate facts merge into one official fact with multiple evidence rows.
- Low-confidence candidates are counted and force the build into `review_required`.
- Successful builds have correct node/fact/edge/evidence counters.
