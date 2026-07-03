# Task Package: Course Textbook Task Outline Persistence

## Task name

Task Outline profile and node persistence for training-operation textbooks.

## Source context

- `ARCHITECT.md`: knowledge processing input is `normalized_asset_ref`; do not
  add reverse pointers on asset/version/ref; `knowledge_chunk.normalized_ref_id`
  remains the unified retrieval and traceability anchor.
- `SPEC.md`: Knowledge Pipeline P0 uses NEXUS-owned `knowledge_chunk`; search and
  QA must preserve citation traceability.
- `docs/course_textbook_knowledge_processing_design.md`: task-operation
  textbooks require Task Outline domain tables, while projected chunks stay in
  the unified `knowledge_chunk` table.
- `docs/course_textbook_knowledge_processing_implementation_plan.md`: Package A
  scopes the initial implementation to persistence contracts.
- `WORKFLOWS.md`: new data model changes require a bounded task package and Data
  Model Gate review.

## Goal

Add the persistence foundation for Task Outline processing so later slices can
store textbook subtype/profile decisions and project/task/step/artifact trees
without changing the existing asset/version/knowledge_chunk contracts.

## Scope

- `nexus-app` ORM models for `task_outline_profile` and `task_outline_node`.
- Alembic migration for both tables, foreign keys, indexes, and uniqueness.
- Pydantic/domain schemas for profile and node DTOs.
- Minimal application service helpers to upsert a profile, replace nodes
  idempotently, and list nodes for a normalized ref/profile.
- Focused backend tests for persistence, constraints, JSON defaults, and no
  reverse-pointer drift.
- Documentation under this task package only.

## Out of scope

- Textbook subtype detection.
- Task Outline extraction from normalized blocks.
- Task-aware `knowledge_chunk` projection.
- Evidence Graph candidate-selection changes.
- Console Task Outline view or manual maintenance.
- Enterprise training task automatic recognition or extraction.

## Forbidden changes

- Do not introduce enterprise IAM or a custom LLM gateway.
- Do not use raw files, raw JSON, or MinerU raw output as Task Outline input.
- Do not add `task_chunk` or `training_task_chunk`.
- Do not add reverse pointers such as `asset.current_version_id`,
  `asset_version.normalized_ref_id`, `normalized_asset_ref.task_outline_id`, or
  `knowledge_chunk.task_outline_node_id`.
- Do not change existing `course_textbook -> textbook_kb` governance mapping.
- Do not add P1/P2 features beyond the persistence foundation.

## Deliverables

- ORM models.
- Alembic migration.
- Pydantic/domain schemas.
- Application service helpers.
- Tests.

## Acceptance

- Migration creates and drops the Task Outline tables cleanly.
- A profile and a small project/task/step tree can be persisted and queried.
- Only one effective profile exists per `(normalized_ref_id, asset_profile)`.
- Node tree ordering is deterministic.
- JSON defaults are isolated per row.
- No reverse-pointer columns are added to `document_asset`, `document_version`,
  `normalized_asset_ref`, or `knowledge_chunk`.

## Review Gates

- Data Model Gate before merge.

## Verification

Run focused backend tests after implementation:

```bash
cd nexus-app
uv run pytest tests/task_outline
```

