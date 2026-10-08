# Task Package: API Data Sync W7 Logs And Audit

## Goal

Make sync runs searchable and auditable from the plan-level Console drawer while preserving historical snapshots and keeping sensitive values out of log responses.

## Scope

- Exact run-ID lookup alongside existing Provider, status, and created-time filters.
- Administrator-only run log read API with a bounded query snapshot summary and allowlisted audit fields.
- Plan-level run filters, paginated records, and a run-detail drawer showing snapshot hash/version, progress, controls, and linked audit history.
- Historical access after plan soft deletion, without changing stored runs.

## Forbidden Changes

- No result sink, raw response storage, provider registration, or new run-event table.
- No secret-bearing query values, idempotency-key hashes, or large upstream bodies in log responses.
- No external calls inside database transactions.

## Review Gates

- API Contract, Permission And Audit, and P0 Frontend UX review before merge.

## Verification Evidence

- `nexus-api` data sync log/run/control/plan suite: 16 tests passed.
- `nexus-app` audit sanitizer suite: 15 tests passed.
- Console TypeScript, focused ESLint, and production build passed. The sandboxed build could not fetch Google Fonts; the allowed network build passed.
- API Contract, Permission And Audit, and Frontend UX Review Gates remain pending human review.
