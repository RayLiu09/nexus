# Task Package: Evidence-grounded KG Contract Update

## Scope

- Update `docs/evidence_grounded_knowledge_graph_design.md` to clarify the current-stage graph profiles, extraction routing by `anchor_role`, and full-document semantic coverage requirement.
- Remove deprecated RAGFlow-specific columns from `knowledge_chunk`:
  - `ragflow_chunk_method`
  - `ragflow_doc_id`
  - `ragflow_chunk_id`
- Keep RAGFlow/index backend execution state in `index_manifest` and adapter-local payloads only.

## Boundaries

- Do not redesign the existing RAGFlow adapter in this slice.
- Do not remove `index_manifest.ragflow_doc_id`; it is index backend state, not chunk identity.
- Do not change `knowledge_chunk.normalized_ref_id` lineage.
- Do not implement the full graph builder yet; this package only freezes the graph construction contract and removes deprecated chunk fields.

## Acceptance

- `KnowledgeChunk` ORM no longer exposes the three deprecated RAGFlow fields.
- Alembic migration drops the three `knowledge_chunk` columns and the chunk-level RAGFlow index when present.
- Existing chunk builder/tests no longer pass chunk-level RAGFlow fields.
- Public search enrichment no longer joins `knowledge_chunk` by `ragflow_chunk_id`.
- Graph design doc states that graph construction must cover the full semantic scope of the source asset, using chunks only as evidence windows and locator anchors.
