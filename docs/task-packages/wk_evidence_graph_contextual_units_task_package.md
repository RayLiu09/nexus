# Task Package: Evidence Graph Contextual Extraction Units

## Task name

Use contextual extraction units for Evidence Graph builds.

## Source context

- `ARCHITECT.md`: Evidence-grounded KG is linked to `normalized_asset_ref` and
  `knowledge_chunk` evidence locators; governance inputs must be normalized
  assets, not raw files.
- `SPEC.md`: Evidence-grounded KG is a bounded extension over a complete
  normalized ref; Console rendering and build reads remain internal APIs.
- `docs/evidence_grounded_kg_implementation_plan.md`: GraphBuild must cover the
  full normalized ref, not a Top-K or page-level subset.
- `docs/evidence_graph_contextual_unit_design.md`: RAG chunks remain evidence
  units, while graph extraction uses section/window contextual units.

## Goal

Reduce Evidence Graph over-fragmentation by grouping selected graph candidate
chunks into contextual extraction units before extraction, while preserving
chunk-level evidence traceability.

## Scope

- `nexus-app/nexus_app/evidence_graph/units.py`: new grouping module.
- `nexus-app/nexus_app/evidence_graph/extractors.py`: unit-aware extraction
  entry point and prompt input.
- `nexus-app/nexus_app/evidence_graph/processor.py`: group units before
  extraction and report grouping quality summary.
- Focused tests under `nexus-app/tests/`.
- Design document under `docs/`.

## Out of scope

- Database migrations.
- New graph tables.
- Public/open graph APIs.
- Full multi-chunk evidence persistence in `knowledge_graph_evidence`.
- Console graph overview/focused rendering changes.
- Changing RAG chunk size or RAGFlow integration.

## Forbidden changes

- Do not use raw files, raw JSON, or MinerU raw output as graph input.
- Do not turn Evidence Graph builds into Top-K retrieval over chunks.
- Do not include Task Outline chunks marked `graph_candidate=false` or
  `domain_model=task_outline.v1`.
- Do not add reverse pointers to normalized refs, versions, or chunks.
- Do not break existing chunk-level evidence locators.

## Deliverables

- Runtime `GraphExtractionUnit` grouping.
- Unit-aware extraction path.
- `quality_summary.unit_grouping` in graph builds.
- Tests for section grouping, window splitting, extraction compatibility, and
  processor summary.

## Acceptance

- Existing Evidence Graph tests pass.
- New tests prove multiple chunks under one section are extracted as one unit.
- Existing graph persistence remains evidence-bound to `knowledge_chunk`.
- Candidate selection still covers the full normalized ref.

## Verification

```bash
cd nexus-app
uv run pytest tests/test_evidence_graph_candidates.py \
  tests/test_evidence_graph_extractors.py \
  tests/test_evidence_graph_processor.py \
  tests/test_evidence_graph_persist.py
```
