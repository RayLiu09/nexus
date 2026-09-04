# Task Package: Teaching Standard Course Library Slice 0 Contract Baseline

## Status

Completed on 2026-09-04. Contract baseline and corpus fixture tests passed;
no persistence, API, retrieval, or Console implementation was introduced.

## Goal

Freeze the implementation contract and reviewed fixture corpus required before
the teaching-standard and course-library schema/migration work begins.

## Scope

- `docs/contracts/teaching_standard_course_library_v1.md`.
- Existing teaching-standard test fixture inventory and expected assertions.
- Contract-only tests or schemas where they do not require new database tables.
- The Slice 0 status update in the master task package.

## Out Of Scope

- SQLAlchemy models, Alembic migration, extractor/writer implementation,
  Pipeline/worker changes, backfill, any API, query/retrieval/index work, and
  `nexus-console` work.

## Frozen Decisions

- One standard is reviewed and activated as a whole: `review -> active`;
  later revision: `superseded`.
- The persisted standard-course business contract contains exactly 18
  course-owned fields. Major code, major name, and education level remain on
  the parent standard only.
- A core-table row maps to one course whose name is the literal
  `课程涉及的主要领域` value.
- One standard makes at most one LLM derivation call. Deterministic fields are
  never LLM-produced.

## Deliverables

- Field, state, evidence, source, and batch-derivation contract.
- Required sample corpus and expected-value matrix.
- Planned audit event names and failure-code taxonomy.

## Acceptance

- The contract distinguishes domain status from existing asset-version status.
- The corpus covers high vocational, secondary vocational, vocational
  undergraduate, cross-page core table, structural course admission, and
  no-tool cases.
- No unapproved API, retrieval, Console, or persistence changes are made.
