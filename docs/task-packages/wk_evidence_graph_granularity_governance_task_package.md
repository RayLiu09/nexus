# Task Package: Evidence Graph Granularity Governance

## Task name

Strengthen build-scope granularity governance for Evidence Graph persistence.

## Source context

- `docs/evidence_graph_contextual_unit_design.md`: Stage 3 calls for graph
  granularity governance after contextual extraction units and multi-chunk
  evidence persistence.
- `docs/evidence_grounded_knowledge_graph_design.md`: graph construction must
  include build-scope merge / normalization over the complete normalized ref;
  chunks are evidence anchors, not local graph scopes.
- `nexus_app.evidence_graph.persist`: current persistence already merges exact
  duplicate fact keys and writes evidence-bound graph rows.
- User decision: optimize graph granularity now, but do not connect Evidence
  Graph into retrieval/search/QA yet. Retrieval consumption stays out of scope
  until the search design is finalized.

## Goal

Reduce noisy, overly local, or redundant graph rows after extraction without
changing the database schema or weakening chunk-level evidence traceability.
Move the official graph closer to a RAG context-completion layer by retaining
only facts with enough semantic value for document-level context, while keeping
fine-grained extraction output visible through diagnostics counters.

## Scope

- Add a build-scope candidate governance stage between extraction and
  persistence in `nexus-app/nexus_app/evidence_graph/`.
- Score/filter candidates by semantic salience, evidence breadth, context role,
  generic entity names, weak predicates, and per-chunk over-fragmentation.
- Preserve retained candidate context metadata in `fact.qualifiers` using
  existing JSON fields; no schema migration.
- Derive stable `chunk_context_links` in build diagnostics so later retrieval
  design can consume chunk-to-graph context without changing the current search
  path.
- Add a build quality gate that can mark persisted but over-localized graph
  builds as `review_required`.
- Enhance deterministic entity, predicate, and literal canonicalization in
  `nexus-app/nexus_app/evidence_graph/persist.py`.
- Filter weak fact candidates before graph rows are written.
- Track duplicate evidence rows, canonicalization/weak-filter counters, and
  build-scope granularity metrics in `quality_summary`.
- Strengthen body/unit extraction prompt to request core context facts instead
  of exhaustive local triples.
- Add focused persistence tests.
- Update the contextual unit design document with the Stage 3 implementation
  status.

## Out of scope

- LLM-based canonicalization.
- New graph tables or migrations.
- Retrieval/search/QA integration with Evidence Graph context.
- New persisted `chunk_context_link` table or migration.
- Console overview/focused graph redesign.
- Cross-build or cross-asset graph merge.

## Acceptance

- Equivalent metric literals such as `2.9%`, `2.9％`, and `2.9 %` merge into
  one fact.
- Equivalent predicates such as `发布` / `印发` / `出台` merge into one relation.
- Weak `MENTIONS` facts with poor semantic value are rejected and counted.
- Exhaustive local mentions from one chunk/window are filtered before official
  persistence and counted in `quality_summary.build_scope_governance`.
- Retained candidates carry context metadata such as `context_role`, `salience`,
  `context_relation`, `context_priority`, `context_reason`, and
  `context_for_chunk_ids` in qualifiers.
- Graph build diagnostics include facts-per-chunk, single/multi-chunk fact
  ratios, generic-entity ratio, context-link count, and per-chunk overrun
  counts.
- Graph build diagnostics include a stable `chunk_context_links` array.
- Persisted builds with graph rows but poor RAG-context suitability can finish
  as `review_required` with `quality_summary.graph_quality_gate` reasons.
- Duplicate evidence rows from overlap windows are skipped and counted.
- Existing Evidence Graph focused tests pass.
