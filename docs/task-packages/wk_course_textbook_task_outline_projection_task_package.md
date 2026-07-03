# Task Package: Course Textbook Task Outline Chunk Projection

## Task name

Project Task Outline nodes to unified `knowledge_chunk`.

## Source context

- `docs/course_textbook_knowledge_processing_design.md`: task-operation
  textbook nodes must project into the unified `knowledge_chunk` table; no
  `task_chunk` or `training_task_chunk` storage.
- `docs/course_textbook_knowledge_processing_implementation_plan.md`: Package C
  owns projection service, metadata contract, and idempotent replacement.
- `docs/task-packages/wk_course_textbook_task_outline_task_package.md`: Package A
  added Task Outline persistence.
- `docs/task-packages/wk_course_textbook_task_outline_extraction_task_package.md`:
  Package B added deterministic detection and extraction.
- `ARCHITECT.md`: `knowledge_chunk.normalized_ref_id` links chunks to
  `normalized_asset_ref`; source provenance must preserve `source_block_ids`
  and `locator`; external index backend ids must not live on chunks.

## Goal

Convert high-value Task Outline nodes for training-operation textbooks into
retrieval-ready `knowledge_chunk` rows while preserving the existing
`textbook_kb` knowledge type and citation contract.

## Scope

- `nexus-app/nexus_app/task_outline/projector.py`.
- Service helpers to replace projected chunks idempotently for a Task Outline
  profile.
- Tests for projection rules, metadata contract, locator/source propagation,
  and idempotency.

## Out of scope

- Evidence Graph candidate-selection changes.
- Index manifest stale handling.
- RAGFlow upload/index execution.
- Console/API changes.
- Manual editing/rebuild workflow.
- New `chunk_type` or `chunking_strategy` enum values.

## Forbidden changes

- Do not add a task-specific chunk table.
- Do not change the `knowledge_chunk` schema.
- Do not store external index backend ids on `knowledge_chunk`.
- Do not add reverse pointers from `knowledge_chunk` to `task_outline_node`;
  use `chunk_metadata.outline_node_id`.
- Do not make task-outline chunks graph candidates by default.
- Do not remove existing theory-textbook semantic chunk behavior.

## Deliverables

- Task Outline chunk projection service.
- Idempotent replacement helper.
- Tests.

## Acceptance

- Must project `task`, `task_section`, `operation_step`, and `task_artifact`
  nodes.
- May project `project`, `assessment`; may skip empty/noise nodes.
- Projected chunks use:
  - `knowledge_type_code = textbook_kb`
  - `chunk_type = semantic_block`
  - `chunking_strategy = semantic_repack`
  - `source_kind = extracted_from_normalized`
  - `chunk_metadata.domain_model = task_outline.v1`
  - `chunk_metadata.semantic_variant = task_outline_repack`
  - `chunk_metadata.outline_node_id = <node id>`
  - `chunk_metadata.section_processing_profile = task_outline`
  - `chunk_metadata.graph_candidate = false`
- Source block ids and locator are copied from the Task Outline node.
- Reprojection for the same profile replaces previous `task_outline.v1`
  projected chunks without duplicating rows.

## Review Gates

- RAGFlow Integration Gate before merge if this projection is wired into an
  indexing path.

## Verification

```bash
cd nexus-app
uv run pytest tests/task_outline
```

