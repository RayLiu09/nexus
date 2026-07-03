# Task Package: Course Textbook Task Outline Detection And Extraction

## Task name

Course textbook subtype detector and minimal Task Outline extractor.

## Source context

- `docs/course_textbook_knowledge_processing_design.md`: task-operation
  textbooks should route to Task Outline, theory textbooks remain graph-ready,
  and ambiguous assets should not be forced into a task model.
- `docs/course_textbook_knowledge_processing_implementation_plan.md`: Package B
  owns subtype detection, heading/key-label normalization, tree extraction,
  locator binding, and quality metrics.
- `docs/task-packages/wk_course_textbook_task_outline_task_package.md`: Package A
  has added `task_outline_profile` and `task_outline_node` persistence.
- `ARCHITECT.md`: knowledge processing input remains `normalized_asset_ref` and
  downstream traceability requires `normalized_ref_id`, `source_block_ids`, and
  `locator`.

## Goal

Provide deterministic first-pass processing for normalized `course_textbook`
documents so training-operation textbooks can produce a minimal Task Outline
tree over projects, tasks, sections, operation steps, and artifacts.

## Scope

- `nexus-app/nexus_app/task_outline/` detector, normalizer, extractor, and
  quality helpers.
- Focused tests for subtype routing and outline extraction.
- Pure Python processing over `normalized_document.blocks[]` /
  `body_markdown`-equivalent payloads.

## Out of scope

- Persisting extractor results into jobs/workers beyond service helpers already
  available from Package A.
- Projecting outline nodes to `knowledge_chunk`.
- Evidence Graph admission changes.
- Console/API changes.
- LLM extraction.
- Enterprise training task automatic extraction.

## Forbidden changes

- Do not use raw files, raw JSON, or MinerU raw output as input.
- Do not bypass `normalized_asset_ref`.
- Do not add task-specific chunk tables.
- Do not change `knowledge_chunk` schema.
- Do not force ambiguous/theory textbooks into `training_operation`.
- Do not add P1/P2 scope.

## Deliverables

- Textbook subtype detector.
- Heading/key-label normalization helpers.
- Minimal Task Outline extraction.
- Quality metric calculation.
- Unit tests and verification evidence.

## Acceptance

- Training-operation fixtures classify as `training_operation`.
- Theory fixtures classify as `theory_knowledge`.
- Ambiguous fixtures classify as `unknown` or `hybrid`.
- A training-operation fixture generates project, task, task-section,
  operation-step, and task-artifact nodes.
- High-value nodes carry `source_block_ids`.
- Locator is aggregated from block page/bbox data when present.
- Quality metrics include at least `locator_coverage`,
  `chunk_projection_coverage`, `artifact_binding_rate`, and
  `orphan_block_ratio`.

## Review Gates

- No new Review Gate beyond implementation review unless this slice is wired
  into jobs or indexing. Data model was covered by Package A.

## Verification

```bash
cd nexus-app
uv run pytest tests/task_outline
```

