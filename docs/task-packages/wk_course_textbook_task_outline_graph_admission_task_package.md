# Task Package: Task Outline Evidence Graph Admission Control

## Task name

Skip Task Outline chunks from default Evidence Graph candidate selection.

## Source context

- `docs/course_textbook_knowledge_processing_design.md`: task-operation
  textbooks should default to Task Outline and not be recommended for Evidence
  Graph.
- `docs/course_textbook_knowledge_processing_implementation_plan.md`: Package D
  owns candidate-selector skip logic and explicit skip reasons.
- `docs/task-packages/wk_course_textbook_task_outline_projection_task_package.md`:
  Package C projects task-outline chunks with
  `chunk_metadata.domain_model=task_outline.v1`,
  `section_processing_profile=task_outline`, and `graph_candidate=false`.
- `ARCHITECT.md`: Evidence-grounded KG consumes eligible `knowledge_chunk`
  evidence windows for a complete `normalized_asset_ref`.

## Goal

Prevent task-operation guidance chunks projected from Task Outline from entering
default Evidence Graph candidate selection, while preserving existing
theory-textbook semantic chunk behavior.

## Scope

- `nexus-app/nexus_app/evidence_graph/candidates.py`.
- Focused tests for task-outline skip reasons and existing graph candidate
  behavior.

## Out of scope

- Console warning/confirmation UI.
- Hybrid chapter-level graph selection.
- New graph profiles.
- Public/open APIs.
- Task Outline chunk projection.

## Forbidden changes

- Do not query Top-K chunks for Evidence Graph builds.
- Do not make task-outline chunks graph candidates by default.
- Do not change the `knowledge_chunk` schema.
- Do not remove existing anchor-role/quality/image skip checks.
- Do not mix Evidence-grounded KG with Pipeline B capability graph staging.

## Deliverables

- Candidate selector skip logic for:
  - `graph_candidate=false`
  - `section_processing_profile=task_outline`
  - `domain_model=task_outline.v1`
- Explicit skip reason: `task_outline_not_graph_candidate`.
- Tests.

## Acceptance

- Task-outline chunks are skipped with
  `task_outline_not_graph_candidate`.
- Normal semantic body chunks are still selected.
- Existing low-quality, empty, unsupported role, and table/image skip behavior
  remains intact.

## Review Gates

- RAGFlow Integration Gate before merge if graph build or indexing workflows
  are changed beyond candidate selection.

## Verification

```bash
cd nexus-app
uv run pytest tests/test_evidence_graph_candidates.py tests/task_outline
```

