# Task Package: Professional Teaching Standard And Course Library

## Status

Slice 0 contract baseline, Slice 1 standard fact projection, and Slice 2
course fact projection are completed. Slice 2 evidence is recorded under
`wk_teaching_standard_course_library_slice2_task_package.md`. This package
remains the master scope and acceptance baseline for subsequent slices.

## Source Context

- `docs/reference-1.md`: field contract for the professional teaching-standard
  library, its 18-field persisted course library, whole-standard review lifecycle, and
  one batch LLM derivation per professional standard.
- `AGENTS.md`: all domain extraction consumes `normalized_document` through
  `normalized_asset_ref`; raw files and MinerU output are never valid inputs.
  Assetization and normalization remain separate, and mutations are auditable.
- `ARCHITECT.md`: domain projections use single-direction relations from
  `normalized_asset_ref`; asset/version reverse pointers are prohibited.
- Existing `teaching_standard.v1` capability graph and `course_standard.v1`
  document graph remain separate capabilities and are not replaced.

## Goal

Build a versioned, evidence-bound `teaching_standard_library` and its standard
course library from a governed `normalized_document`. This is a national or
industry-standard baseline, not a statement that an institution actually
offers a course. Institution-owned courses remain `talent_training_plan_course`.

## Frozen Contract

```text
normalized_document
  -> teaching_standard_library
     -> teaching_standard_occupation
     -> teaching_standard_rule
     -> teaching_standard_course
     -> teaching_standard_course_derivation (internal provenance)
```

- Library status is a domain-projection state, distinct from asset-version
  state: `review -> active -> superseded`.
- Every new standard projection begins as `review`. Business experts approve
  the complete standard and its complete course set; only then it becomes
  `active`. A later effective standard can supersede the earlier projection.
- Courses have no `confidence_level`, `need_confirm`, or `review_status`.
  Parent-standard status exclusively controls their business availability.
- Each core-course source row maps to one logical course, and its
  `standard_course_name` is copied literally from `课程涉及的主要领域`. Later
  rows matching the same course unique key append evidence rather than create
  another course row.
- The persisted course contract has exactly 18 course-owned fields:
  `course_id`, `standard_course_name`, `course_type`,
  `suggested_total_hours`, `suggested_practice_hours`,
  `suggested_hours_range`, `hours_setting_basis`,
  `typical_work_task_description`, `teaching_content_requirement`,
  `knowledge_tags`, `skill_tags`, `tool_tags`, `literacy_tags`,
  `match_keywords`, `match_text`, `source_standard`, `source_section`, and
  `source_page`.
- `major_code`, `major_name`, and `education_level` remain only on the parent
  `teaching_standard_library`. Internal keys, ref/version IDs, source sequence,
  evidence locators, provenance, timestamps, and audit columns do not expand
  that 18-field persisted contract.
- Public/internal query APIs, retrieval, vector/chunk/index work, and every
  `nexus-console` page or action are excluded.

## Scope

- `nexus-app` domain models and Alembic migration for standard, occupation,
  rule, course, and internal derivation-provenance rows.
- A new `nexus_app.teaching_standard_library` package containing schemas,
  deterministic extraction, batch derivation, writer, validation, and a
  whole-standard lifecycle command.
- Pipeline A/worker wiring after normalized-document persistence, domain audit
  events, idempotent rebuild behavior, a dry-run-first historical backfill,
  and focused tests.
- Contract-document changes required by the new persisted projection.

## Out Of Scope

- Any `/v1` or `/internal/v1` read/filter/query endpoint.
- Search, semantic chunks, pgvector, index manifests, reranking, query router,
  or RAG work.
- `nexus-console` routes, pages, components, review dialogs, or actions.
- Institution-course alignment; global industry/occupation/position/certificate
  master data; and changes to `course_standard.v1`, `major_profile.v1`,
  `talent_training_plan.v1`, or the existing capability graph.

## Forbidden Changes

- Do not use raw file, raw JSON, MinerU output, or page images as post-
  normalization extraction input.
- Do not add asset/version reverse pointers or let LLM output change official
  governance or publish a standard as `active`.
- Do not call LLM once per course when the standard's candidate courses fit in
  the single batch contract.
- Do not restore course-level review fields or treat the source-standard course
  name as a global canonical course master.

## Implementation Slices

### Slice 0: Contract And Corpus Baseline (5-7 person-days)

Freeze table names, state transitions, constraints, audit events, batch schema,
and fixtures. Build a reviewed corpus covering secondary vocational, higher
vocational, vocational undergraduate, a cross-page core table, structural
course admission, and a standard without explicit tool names.

Acceptance: the 18 course-owned fields are contract-tested; expected standard/course facts
are business-expert baselined; required Review Gate inputs are ready.

### Slice 1: Standard Fact Projection (10-14 person-days)

Add `teaching_standard_library`, occupation child rows, rule rows, migration,
deterministic heading/occupation extraction, evidence locators, validation, and
idempotent writer. Default the new standard to `review`.

Acceptance: one valid normalized ref produces one idempotent review-state
projection; missing source facts remain empty with diagnostics, never guessed;
source-scoped values create no global master data.

### Slice 2: Course Fact Projection (completed)

Add course/provenance rows. Extract foundation, core, and extension groups;
merge core-table continuations by sequence and source-table identity; and admit
courses only from the three recognized professional-course sections. Copy core
course names from `课程涉及的主要领域`. Enforce
`UNIQUE(library_id, course_type, standard_course_name)` and merge all matching
source evidence onto that logical course. Do not use name-based exclusion
blacklists or persist parent `major_code`, `major_name`, or `education_level`
on course rows.

Acceptance: every accepted core-table row maps to one evidence-bound course;
foundation/extension names stay literal with unavailable task text empty;
rebuilds are idempotent, same-key source occurrences retain all evidence on one
course, and no course is filtered by course-name heuristics.

### Slice 3: One-Batch Derivation And Validation (10-14 person-days)

Implement a strict LLM request/response for one standard's training-goal
summary and all candidate-course tag/complexity results. Deterministic code
creates IDs, normalizes/deduplicates tags, calculates suggested hours from
rules, validates ratios/ranges, and renders match fields. Persist input/output
hashes, `ai_prompt_profile` reference, evidence bindings, and failure reasons.

Acceptance: each complete standard makes at most one LLM derivation call;
malformed output cannot change source facts; deterministic fields never call
LLM; practice hours do not exceed total hours.

### Slice 4: Lifecycle And Audit Completion (8-11 person-days)

Extend the Slice-2 normalized-document projection wiring with idempotent
replacement across new normalized refs and audited domain commands for
`review -> active` and supersession, and regression coverage. Do not add a
transport route or UI for these commands in this task cycle.

Acceptance: repeated processing is idempotent; newer source versions preserve
old projections; only a business-expert domain command activates a standard;
existing capability-graph construction is unchanged.

### Slice 5: Historical Backfill And Review Evidence (6-10 person-days)

Create a dry-run-first backfill command, pilot it only after approval, and
report bounded counts/stable failure reasons. Capture corpus comparison and
whole-standard approval evidence.

Acceptance: dry run has no writes; unchanged input does not repeat derivation;
only business-expert-approved standards become `active`.

## Cost And Delivery

| Boundary | Engineering | Business expert | Calendar |
| --- | ---: | ---: | --- |
| Slices 0-2: review-state facts | 27-37 person-days | 10-18 person-days | 4-6 weeks |
| Slices 0-4: adds derivation/lifecycle | 45-62 person-days | 18-34 person-days | 7-10 weeks |
| Slices 0-5: adds pilot backfill/evidence | 51-72 person-days | 28-54 person-days | 9-12 weeks |

Assumes two backend/data engineers, shared test support, and timely business-
expert corpus review. Estimates explicitly exclude all APIs, retrieval, and
Console work.

## Deliverables

- Frozen schema/migration, deterministic extractor/writer, strict one-call-
  per-standard derivation, lifecycle command/audit trail, worker wiring,
  dry-run backfill, focused tests, and Review Gate evidence.

## Required Review Gates

- Data Model Gate, AI Governance Gate, Rule Engine Gate, Version State Gate,
  and Permission And Audit Gate for lifecycle commands.

## Verification

Exact test paths are created in Slice 0. The minimum planned command is:

```bash
cd nexus-app
uv run pytest tests/teaching_standard_library tests/pipeline/test_teaching_standard_library.py
```

No frontend build, Console test, API contract test, query performance test, or
semantic-index test is part of this task package.
