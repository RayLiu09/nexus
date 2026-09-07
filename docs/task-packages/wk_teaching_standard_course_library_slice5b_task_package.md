# Task Package: Teaching Standard Library Slice 5B Data Corrections

## Status

Implementation and the approved historical correction are complete. This
correction follows the approved Slice 5A historical rebuild and remains limited
to review-state teaching-standard data.

## Objective

Correct three corpus-backed issues in the professional teaching-standard read
model without repeating course LLM derivation:

- remove the unused `teaching_standard_library.standard_id` field;
- parse professional category/class codes from parenthesized table values and
  persist clean names without Markdown header/separator noise;
- store the four course tag arrays as PostgreSQL JSONB so database text output
  contains readable Chinese rather than JSON `\uXXXX` escapes.

## Owned Files

- teaching-standard library ORM, schemas, extractor, writer, and derivation
  compatibility code;
- Alembic revision `20260907_0099`;
- teaching-standard focused tests and contract documentation.

## Frozen Boundaries

- `major_code`, `major_name`, and `education_level` remain parent-owned.
- The course library retains its existing 18 business fields and uniqueness
  constraints.
- Tag values remain JSON arrays of Chinese strings; this change only replaces
  PostgreSQL JSON text storage with JSONB binary storage.
- Historical classification correction uses normalized-document evidence and
  the existing backfill path with `--no-llm`; existing successful derived
  fields remain. A standard whose completed input hash predates the current
  evidence contract is re-derived only through the one-whole-standard path.
- Existing completed derivation hashes with a formerly-null `standard_id`
  remain reusable through canonical-hash compatibility.

## Explicitly Excluded

- Lifecycle activation, review UI, APIs, retrieval, indexing, and Console work.
- Reclassification of source assets or changes to non-teaching-standard models.
- Per-course LLM calls or re-derivation of already reusable whole-standard
  results.

## Acceptance

- The database and ORM no longer expose `standard_id`.
- Category/class names contain only the clean Chinese name and their codes are
  populated from the same evidence text.
- PostgreSQL `knowledge_tags`, `skill_tags`, `tool_tags`, and `literacy_tags`
  are JSONB and render Chinese directly through `column::text`.
- All 20 historical standards remain `review`; all 537 courses retain their
  derived tags, hours, and match fields.
- Post-correction dry-run reuses all 20 completed derivations with zero LLM
  calls.

## Execution Evidence

- Alembic upgraded from `20260904_0098` to `20260907_0099`.
- The no-LLM source-fact correction rebuilt 20 standards and skipped one
  course-standard false classification.
- Four historical standards with non-current completed input hashes were
  successfully re-derived once each; one additional candidate became reusable
  before execution. No per-course call was made.

## Review Gates

- Data Model Gate: migration drops only the unused parent field and converts
  four tag columns without changing their logical array contract.
- AI Governance Gate: correction makes no model call and preserves completed
  derivation provenance.
- Version State Gate: all projections remain `review`.
