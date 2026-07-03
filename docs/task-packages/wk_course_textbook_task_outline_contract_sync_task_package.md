# Task Package: Course Textbook Task Outline Contract Sync

## Task name

Synchronize root contracts for delivered Task Outline capability.

## Source context

- `docs/course_textbook_knowledge_processing_implementation_plan.md`: section
  10 requires `ARCHITECT.md`, `SPEC.md`, and `readme.md` updates after the
  active Task Outline slice lands.
- Package A-F for course textbook Task Outline are implemented and pushed.

## Goal

Record the active architecture/product baseline for course textbook
training-operation Task Outline processing in the root implementation
contracts, without expanding scope into later hybrid or enterprise training
task slices.

## Scope

- `ARCHITECT.md`:
  - add `task_outline_profile` / `task_outline_node` to active domain objects
  - document Task Outline metadata on unified `knowledge_chunk`
  - document internal rebuild/read API boundary
  - document index stale behavior after projected chunk replacement
- `SPEC.md`:
  - add P0 behavior for course textbook training-operation Task Outline
  - add Console asset-detail read view behavior
  - add acceptance criteria for profile/nodes/chunks/stale index
- `readme.md`:
  - add a short implementation baseline entry.

## Out of scope

- New runtime code.
- New data model, API, or UI behavior.
- Hybrid chapter-level routing.
- Enterprise training task extraction.
- Public/open Task Outline APIs.

## Forbidden changes

- Do not relax normalized input rules.
- Do not introduce raw-file or MinerU raw-output inputs.
- Do not add reverse pointers.
- Do not make Evidence Graph mandatory for all textbooks.
- Do not mark later slices as delivered.

## Acceptance

- Root contracts accurately describe the delivered Task Outline behavior.
- Later-scope hybrid and enterprise training task work remains explicitly
  outside the current active baseline.
- No unrelated draft documents are changed.

## Verification

```bash
git diff --check
```
