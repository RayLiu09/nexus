# Task Package: Talent Training Plan List Performance

## Status

Implementation and data backfill verified; human API/Data Contract and Acceptance Review Gates remain before merge.

## Goal

Reduce the initial load time of `/asset-center/major/training-plans` and fill missing professional identity fields in its persisted read model while preserving visibility, official-classification, pagination, filtering, and response contracts.

## Scope

- Replace global latest-version/ref/governance window scans in this list with plan-scoped indexed lookups.
- Fetch only list fields and a course count; retain full course loading for detail and graph endpoints.
- Add focused API regression tests for superseded versions, refs, governance decisions, and bounded list queries.
- Complete missing major code/name/level from the confirmed finance-commerce catalog in the writer and a dry-run-first historical backfill.
- Derive missing study duration only from explicit normalized-document text or title evidence; audit applied row changes.
- Record query shape and verification evidence here.

## Boundaries

- No schema migration, state transition, governance mutation, new API, or graph behavior change.
- Never overwrite nonempty source values or infer a standard duration from a catalog tuple.
- Open API and internal API response fields remain compatible.
- Asset Center visibility remains identical to the existing count read model.

## Review Gates

- API Contract Gate: verify visibility and latest-classification semantics plus response fields.
- Data Contract Gate: verify catalog completion, ambiguity handling, source-backed duration, and idempotent audit.
- Acceptance Gate: run focused API/application tests and review query count and SQL shape.

## Verification Evidence

- The list now uses two SQL statements instead of three, with no global `row_number()` scan or course-detail load. The current database returns the same 22 catalog-visible official plans.
- Five direct read-only list calls against the current database measured 134.9 ms cold and 31.9-33.7 ms on the four subsequent calls. This measures the backend list function, not browser render or network time; no pre-change wall-clock baseline was captured.
- The dry-run-first backfill scanned 85 projections and applied changes to 19: 10 major codes, four education levels, and nine source-backed study durations. It wrote one audit event per changed plan. The follow-up dry run found zero further candidates and no normalized-document read failures.
- In the 22 visible plans, two codes remain blank because the catalog does not identify those names uniquely, and four durations remain blank because there is no explicit matching duration evidence. All 22 have major name and education level.
- Focused application tests: 29 passed. Focused API tests: 13 passed. `git diff --check` passed.
