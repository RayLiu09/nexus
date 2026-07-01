# Task Package: Evidence-grounded KG Candidate Selection

## Source Context

- `docs/evidence_grounded_kg_implementation_plan.md`: Task Package B requires `GraphProfileConfig`, five supported profiles, full normalized-ref semantic chunk loading, and grouping by `anchor_role`.
- `docs/evidence_grounded_knowledge_graph_design.md`: graph construction must cover the complete semantic scope of `normalized_ref_id`; chunks are extraction windows and evidence anchors, not local graph scopes.
- `ARCHITECT.md`: Evidence-grounded KG input is `normalized_asset_ref`; `knowledge_chunk` provides semantic windows, source block ids, and locators.

## Goal

Provide the deterministic candidate-selection layer that later extractor slices can consume. The selector must return every eligible semantic chunk for a normalized ref and must not depend on search results, UI pagination, Top-K retrieval, or user-selected visible chunks.

## Scope

- `nexus-app/nexus_app/evidence_graph/profiles.py`: graph profile definitions and extractor routing metadata.
- `nexus-app/nexus_app/evidence_graph/candidates.py`: full-ref candidate chunk selector.
- `nexus-app/tests/`: unit tests for profile coverage, role routing, full-scope selection, grouping, and skip reasons.
- `docs/evidence_grounded_kg_implementation_plan.md`: mark Task Package B as started.

## Out Of Scope

- LLM/rule extractor implementation.
- Candidate fact schema validation.
- Entity merge, evidence binding, graph quality gates, and graph persistence beyond the build metadata already added in Task Package A.
- Internal API and Console views.

## Forbidden Changes

- Do not query only Top-K chunks.
- Do not accept current-page or manually selected chunks as the GraphBuild input scope.
- Do not include `table_overview` in formal candidate selection by default.
- Do not mix Evidence-grounded KG with Pipeline B capability graph staging.
- Do not create new database tables in this slice.

## Deliverables

- Five built-in profiles:
  - `policy_document`
  - `report_document`
  - `textbook`
  - `standard_spec`
  - `sop_document`
- Candidate selection result with:
  - `selected_chunk_count`
  - `skipped_chunk_count`
  - `total_semantic_chunk_count`
  - `candidate_chunks`
  - `by_anchor_role`
  - `skipped_by_reason`
- Extractor route hints for later slices, especially `body -> LLM`.

## Acceptance

- For a sample normalized ref, selected count equals all eligible semantic chunks for that ref.
- `table_overview`, empty content, low-quality chunks, and non-semantic decorative images are skipped with reasons.
- `body` candidates route to an LLM extractor.
- The selector preserves `chunk_index` order and has no limit parameter, proving it is not Top-K driven.
