# Task Package: Institutional Major And Course Statistics

## Source Context

- `AGENTS.md`: domain facts must remain evidence-bound to `normalized_document`
  through `normalized_asset_ref`; public APIs are owned by `nexus-api`.
- `ARCHITECT.md`: `major_profile.v1` and `talent_training_plan.v1` are distinct
  Pipeline A projections; structured retrieval is the primary path.
- `docs/open_v1_asset_retrieval_api.md`: existing public profile and plan APIs
  are read-only detail/filter APIs, not cross-domain aggregates.

## Goal

Expose province-level institutional-major offerings and course adoption counts
from available institution profiles and talent-training plans. The statistics
support questions such as regional major coverage, a major's courses, most
commonly offered courses, and courses offered by a majority of institutions.

## Scope

- Add only `province_name` to both institution-facing domain projections.
- Add deterministic, formatting-only `course_stat_key` to both course facts.
- Resolve only standard province-level names; unresolved facts remain excluded
  from province aggregates and are reported as coverage exclusions.
- Add public aggregate endpoints, focused tests, migration, historical
  backfill utility, and API documentation.
- Combine sources with `talent_training_plan` preferred for the same
  institution-major offering; `major_profile` supplements a missing plan.

## Out Of Scope

- Province codes, city/district aggregation, an institution master table, or a
  global course master table.
- LLM-based course alias resolution, low-confidence course merging, review
  queues for aliases, enrolment counts, and historical academic-year trends.
- Console UI and generic Evidence Graph changes.

## Forbidden Changes

- Do not infer province from a raw object or MinerU output; resolve only from
  persisted domain facts / normalized-document-derived fields.
- Do not merge semantically similar course names unless a deterministic
  formatting rule proves equality.
- Do not double count a course supplied by both a plan and a profile for the
  same institution-major offering.
- Do not expose non-available versions through Open APIs.

## Deliverables

- SQLAlchemy model and Alembic migration.
- Deterministic province and course-stat-key helpers plus writers/backfill.
- `/open/v1/major-offerings/aggregate` and
  `/open/v1/major-courses/aggregate`.
- Focused tests and Open API documentation.

## Acceptance

- Province aggregation groups only by `province_name` and reports unresolved
  coverage separately.
- Course aggregation counts a course at most once per institution-major under
  `combined_prefer_plan`.
- A plan replaces a matching profile as the course source; profiles supplement
  offerings with no plan.
- API responses report denominator, threshold, source policy, and coverage.
