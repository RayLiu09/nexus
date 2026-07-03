# Task Package: Task Outline Orchestration And Rebuild

## Task name

Task Outline pipeline orchestration and rebuild endpoint.

## Source context

- `docs/course_textbook_knowledge_processing_implementation_plan.md`: Package F
  owns rebuild trigger, idempotent replacement, projected chunk replacement,
  and index stale marking.
- Package A-E task packages: persistence, extraction, chunk projection, graph
  admission, and Console read view are implemented.
- `ARCHITECT.md`: knowledge processing input remains `normalized_asset_ref`;
  downstream artifacts must preserve `normalized_ref_id`, `source_block_ids`,
  and `locator`.
- `SPEC.md`: job/reprocess/re-governance flows must be idempotent and traceable;
  index status must reflect stale derived content.

## Goal

Provide a single backend orchestration service and internal rebuild API that can
turn an existing normalized document payload into Task Outline profile, nodes,
and task-aware chunks, while marking the relevant index manifest stale after
chunk replacement.

## Scope

- `nexus-app` orchestration service for:
  - detect textbook subtype
  - extract Task Outline
  - upsert profile
  - replace nodes
  - project chunks
  - mark `index_manifest` stale when chunks are replaced
- Internal API:
  - `POST /internal/v1/normalized-refs/{ref_id}/task-outline/rebuild`
- Focused tests for idempotent orchestration and API response.

## Out of scope

- Background worker/job submission.
- Manual node editing.
- Enterprise training task extraction.
- Console rebuild button.
- Public/open API.
- RAGFlow sync execution.

## Forbidden changes

- Do not use raw files or MinerU raw output as input.
- Do not add task-specific chunk tables.
- Do not add reverse pointers.
- Do not change the existing `knowledge_chunk` schema.
- Do not run heavyweight LLM extraction inline.
- Do not make RabbitMQ/Celery required.

## Deliverables

- Orchestration service.
- Rebuild API endpoint.
- Index stale marking for `textbook_kb`.
- Tests.

## Acceptance

- Rebuild from a normalized payload creates/updates one effective profile.
- Rebuild replaces nodes idempotently.
- Rebuild replaces prior Task Outline chunks without duplication.
- Rebuild marks existing `index_manifest(textbook_kb)` as `stale`.
- Non-training-operation textbooks can record profile decisions without creating
  Task Outline nodes/chunks.
- API returns profile, node count, projected chunk count, and quality summary.

## Review Gates

- RAGFlow Integration Gate because chunk replacement affects index input.
- API Contract Gate for the new internal rebuild endpoint.

## Verification

```bash
cd nexus-app
uv run pytest tests/task_outline
```

```bash
cd nexus-api
uv run pytest tests/test_task_outline_api.py
```

