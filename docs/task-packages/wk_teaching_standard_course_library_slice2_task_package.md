# Task Package: Teaching Standard Course Library Slice 2

## Status

Completed on 2026-09-04. This package implements deterministic course fact
projection only.

## Objective

Materialize source-evidenced professional foundation, core, and extension
courses beneath an existing `teaching_standard_library` generated from the
same persisted `normalized_document`.

## Owned Files

- `nexus-app/nexus_app/models.py`
- `nexus-app/alembic/versions/20260904_0097_teaching_standard_course_slice2.py`
- `nexus-app/nexus_app/teaching_standard_library/`
- `nexus-app/nexus_app/worker/runner.py`
- focused Slice-2 tests and fixtures
- teaching-standard course-library contracts and task packages

## Frozen Data Contract

- `teaching_standard_course` stores the 18 course-owned business fields plus
  internal ID, parent ID, source order/hash/evidence, extractor version, and
  timestamps.
- It does not store `major_code`, `major_name`, `education_level`, confidence,
  confirmation, review, or status fields.
- Database uniqueness is
  `UNIQUE(library_id, course_type, standard_course_name)`.
- Multiple source occurrences matching one unique key create one course and
  retain every source binding in `evidence_bindings`.
- Parent `teaching_standard_library.status` exclusively controls business
  availability and remains `review` in this slice.

## Extraction Rules

- Input is only the persisted normalized document addressed through
  `normalized_asset_ref.object_uri`.
- Admit literal entries only from professional foundation, core, and extension
  sections. Do not use course-name exclusion blacklists.
- A core course name is copied literally from `课程涉及的主要领域`.
- Merge cross-page core row fragments only with compatible source-table,
  sequence, course-name, and continuation evidence. Repeated headers are table
  structure, not courses.
- Foundation/extension task and teaching-content fields remain NULL when the
  source does not provide them.
- No LLM call is permitted.

## Persistence Rules

- Rebuilds update courses by the frozen unique key, keep stable internal and
  business course IDs where possible, add new keys, and remove stale keys.
- A source hash change clears future derived fields so stale Slice-3 tags/hours
  cannot survive a changed source fact.
- A missing parent library or unrelated normalized document writes no courses.

## Explicitly Excluded

- Batch LLM derivation, `teaching_standard_derivation_run`, activation or
  supersession commands, historical backfill, query/read APIs, retrieval,
  chunks/indexing, and Nexus Console changes.
- Changes to `major_profile`, `talent_training_plan`, `teaching_standard.v1`,
  `course_standard.v1`, or capability-graph behavior.

## Acceptance

- All three professional course groups are extracted with literal names and
  normalized-document evidence.
- Same-key source occurrences become one row with all evidence bindings.
- Same names in different course types remain separate rows.
- Name-like training/project entries in an admitted professional-course
  section are retained.
- Repeated writes are idempotent and preserve stable course IDs.
- Existing teaching-standard capability graph tests remain green.

## Review Gates

- Data Model Gate: normalized course columns, parent-only shared facts, frozen
  unique key, forward FK, and no course state fields.
- Rule Engine Gate: structural admission and deterministic table/list parsing
  only; no name blacklist or LLM.
- Version State Gate: parent remains `review`; no course status exists.
- Audit Gate: library-generation audit reports course projection counts and
  bounded diagnostics without storing source content.

## Verification

```bash
cd nexus-app
uv run pytest tests/teaching_standard_library tests/test_teaching_standard_graph.py
```

Result: `19 passed`.

- `uv run alembic heads`: `20260904_0097 (head)`.
- `python3 -m compileall`: passed for the course projection, ORM, Worker, and
  migration modules.
- `git diff --check`: passed.
- Black formatted all Slice-2 Python files. Ruff was not available in the
  project environment (`Failed to spawn: ruff`).

## Review Gate Evidence

- Data Model Gate: migration and ORM contain the 18 course-owned fields plus
  internal provenance only; parent major fields and course-level state fields
  are absent. Database metadata tests verify
  `UNIQUE(library_id, course_type, standard_course_name)`.
- Rule Engine Gate: tests cover structural group admission, literal core names,
  preservation of training/project course names, same-key evidence merging,
  cross-page continuation by table ID and sequence, and public-section
  exclusion. The Slice-2 path contains no LLM call.
- Version State Gate: repeat-write tests verify stable course IDs, stale-row
  removal, derived-field invalidation after source changes, and unchanged
  parent `review` state.
- Audit Gate: `TeachingStandardLibraryGenerated` now reports bounded course
  count and diagnostic counts without source text. Worker integration is
  covered by the focused projection test.
