# Task Package: Workbench Summary Accuracy

## Status

Complete.

## Source Context

- `ARCHITECT.md`: Console control-plane APIs belong to `nexus-api` internal
  routes and P0 uses PostgreSQL read queries without a separate statistics
  platform.
- `SPEC.md`: the Workbench summarizes assets, pipeline jobs, governance,
  quality, and current operator attention items.
- Prototype v2.2 NX-01: Workbench figures are operational totals and status
  distributions, not one page of the corresponding ledgers.
- `WORKFLOWS.md`: API contract and frontend UX changes require bounded tests
  and contract documentation.

## Goal

Make every Workbench metric reflect the complete data set while keeping the
page fast and avoiding unbounded list downloads.

## Scope

- Add one read-only `GET /internal/v1/workbench/summary` endpoint.
- Aggregate asset, normalized-reference, raw-object, batch, and job counts in
  SQL.
- Select the latest AI governance run per normalized reference before
  calculating coverage, adoption, review, and quality figures.
- Return at most five current review items for the Workbench decision list.
- Keep recent batch and audit list requests bounded for the activity feed.
- Update the Workbench server component, API types, tests, and contracts.

## Out Of Scope

- New statistics tables, materialized projections, caching, or scheduled
  aggregation jobs.
- Changes to asset, version, governance, quality, or review state machines.
- Changes to Asset Center count semantics or business-list projections.
- A productized operations or monitoring center.

## Forbidden Changes

- Do not remove pagination bounds from existing list endpoints.
- Do not fetch every page of large ledgers into the Console to calculate
  totals.
- Do not treat historical governance runs as current decisions.
- Do not introduce reverse pointers or a persisted Workbench snapshot.

## Deliverables

- Backend summary schema and endpoint.
- Frontend Workbench data mapping.
- Backend aggregation tests and frontend data-contract tests.
- Updated architecture, product, prototype, and repository documentation.

## Acceptance

- Counts remain exact when a resource has more than the default 20-row page.
- Job status figures and pipeline health use all jobs.
- Governance and quality figures use exactly one latest run per normalized
  reference.
- The decision list contains only current review-status runs and is capped at
  five items.
- Workbench no longer requests assets, raw objects, jobs, normalized refs, or
  all governance runs solely for client-side aggregation.
- Focused backend tests, frontend tests, TypeScript, scoped ESLint, real-data
  verification, and `git diff --check` pass.

## Review Gates

- **API Contract Gate**: the new endpoint is read-only, JWT-gated, bounded,
  and has a typed response.
- **Frontend UX Gate**: labels and attention counts match the returned metric
  semantics.
- **Acceptance Gate**: values are checked against direct database aggregates
  on the local data set.

## Verification Evidence

- Backend aggregation and shared review-queue tests:
  `.venv/bin/pytest tests/test_workbench_summary.py tests/test_health.py tests/test_governance_review_pagination.py -q`
  (`4 passed`).
- Route contract test:
  `.venv/bin/pytest tests/test_week2_api.py::test_week2_routes_are_registered -q`
  (`1 passed`).
- Console data-contract tests:
  `pnpm exec vitest run lib/console-data.test.ts lib/governance-runs.test.ts`
  (`2 files, 4 tests passed`).
- `pnpm exec tsc --noEmit`, scoped ESLint, scoped TS/TSX Prettier check,
  and Python compile checks passed.
- Real PostgreSQL/API verification confirmed that
  `workbench.summary.review_required` equals
  `governance-reviews/pending/count`; resource and job totals were above the
  default 20-row list page and remained exact.
- Desktop Chromium verified `/workbench` against same-time summary API values
  for asset, succeeded-job, and failed-job counts with no page errors
  (`1 passed`).
