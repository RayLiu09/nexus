# Task Package: Task Outline Detail Internal APIs

## Task name

Task Outline profile and node detail internal read APIs.

## Source context

- `docs/course_textbook_knowledge_processing_implementation_plan.md` section
  4.4 recommends internal detail endpoints:
  - `GET /internal/v1/task-outline/profiles/{profile_id}`
  - `GET /internal/v1/task-outline/nodes/{node_id}`
- Current implementation already has:
  - `GET /internal/v1/normalized-refs/{ref_id}/task-outline`
  - `POST /internal/v1/normalized-refs/{ref_id}/task-outline/rebuild`

## Goal

Complete the internal read API surface for Task Outline profile and node detail
inspection, using the existing serializers and without changing persistence or
Console behavior.

## Scope

- Add internal profile detail endpoint.
- Add internal node detail endpoint.
- Return stable 404 responses when the profile or node does not exist.
- Reuse existing Task Outline serializers.
- Add focused API tests.

## Out of scope

- Public/open APIs.
- Console routing or new UI screens.
- Manual editing.
- Background rebuild jobs.
- Permission model changes.
- Data model changes.

## Forbidden changes

- Do not read raw files, raw JSON, or MinerU raw output.
- Do not add reverse pointers.
- Do not add task-specific chunk tables.
- Do not change existing envelope or rebuild response shapes.

## Acceptance

- `GET /internal/v1/task-outline/profiles/{profile_id}` returns one serialized
  profile.
- `GET /internal/v1/task-outline/nodes/{node_id}` returns one serialized node.
- Missing profile/node returns 404.
- Existing normalized-ref Task Outline read and rebuild tests still pass.

## Verification

```bash
cd nexus-api
uv run pytest tests/test_task_outline_api.py
```
