# Task Package: Teaching Standard Course Library Slice 1

## Status

Completed 2026-09-04. This package implements only the standard-level fact
projection for the professional teaching-standard library.

## Objective

Create one evidence-bound `teaching_standard_library` projection per valid
`normalized_document`, together with local occupation-facing facts and
numeric-rule facts. Every new projection starts in `review`.

## Owned Files

- `nexus-app/nexus_app/models.py`
- `nexus-app/alembic/versions/20260904_0096_teaching_standard_library_slice1.py`
- `nexus-app/nexus_app/teaching_standard_library/`
- `nexus-app/nexus_app/worker/runner.py`
- `nexus-app/nexus_app/enums.py`
- focused Slice-1 tests and fixtures

## Source And Boundaries

- Input is exclusively the persisted `normalized_document` addressed through
  `normalized_asset_ref.object_uri`.
- Do not read, associate, write, or modify `major_profile`; it is a separate
  professional-introduction model.
- Do not create global industry, occupation, position, or certificate master
  data. All extracted items remain source-scoped children of the library.
- Missing source facts remain NULL/empty and are represented in
  `quality_flags`; the extractor never guesses a standard identifier,
  institution, major, rule, or occupation fact.

## In Scope

- `teaching_standard_library`, `teaching_standard_occupation`, and
  `teaching_standard_rule` ORM models and migration.
- Deterministic extraction of standard identity, education facts,
  occupation-facing declarations, course-structure headings, literal training
  goal evidence, and numeric hour/ratio/internship rules.
- Public-foundation, professional-course, practice, elective, and internship
  rules are independent source constraints with overlapping populations. They
  must never be summed or validated as mutually exclusive hour buckets.
- Schema validation, evidence locators, idempotent replacement writer, worker
  invocation after normalized-document persistence, and generation audit.
- Focused SQLite tests for extraction, validation, writer idempotence, and
  worker-safe domain handling.

## Explicitly Excluded

- `teaching_standard_course`, derivation/provenance tables, course rows, batch
  LLM calls, training-goal summarization, and lifecycle commands.
- Any API, query/filter/read route, retrieval/index/chunk work, backfill, or
  Nexus Console implementation.
- Changes to `teaching_standard.v1` capability graphs, `course_standard.v1`,
  `major_profile`, and `talent_training_plan`.

## Acceptance

- A valid normalized reference creates at most one library row keyed by
  `normalized_ref_id`, with source facts and locators persisted.
- Reprocessing the same normalized reference replaces child facts without
  duplicate rows and leaves the library status as `review`.
- Invalid or unrelated normalized documents create no projection.
- All projected values are evidenced or empty with bounded diagnostics.
- `TeachingStandardLibraryGenerated` is auditable on a successful write.

## Review Gates

- Data Model Gate: forward references only; no reverse asset/version pointer.
- Rule Engine Gate: numeric facts derive only from literal normalized text.
- Version State Gate: only initial `review` is introduced in this slice.
- Permission And Audit Gate: generated projection has traceable audit metadata.

## Review Evidence

- Data Model Gate: three forward-only tables are anchored by
  `normalized_ref_id`/`asset_version_id`; no reverse pointer or `major_profile`
  relation was introduced. Alembic reports the single head
  `20260904_0096`.
- Rule Engine Gate: extraction is deterministic and evidence-bound. Fraction,
  percentage, lower-bound, upper-bound, overlapping-dimension, and two-scope
  internship cases are covered by focused tests. No LLM is called.
- Version State Gate: new projections use `review`; deterministic rebuild
  preserves the stable parent ID and does not activate a standard.
- Permission And Audit Gate: Worker generation writes
  `TeachingStandardLibraryGenerated` with ref, job, counts, status, and bounded
  quality keys. No transport command or permission surface was added.
- Regression result: `15 passed` for Slice-0/Slice-1 tests plus the existing
  teaching-standard capability graph tests.

## Verification

```bash
cd nexus-app
uv run pytest tests/teaching_standard_library tests/test_teaching_standard_graph.py
```
