# Task Package: Talent Demand Report List Performance

## Goal

Reduce initial load latency for the Asset Center talent demand report list while preserving its current visibility, classification, pagination, identity override, tag, and source-link contracts.

## Source Context

- `SPEC.md`: paginated talent demand reports, audited business-expert identity edits, preview and download.
- `ARCHITECT.md`: current version and normalized ref are derived read models; governance targets normalized refs.
- `WORKFLOWS.md`: bounded task package and API Contract and Acceptance Review Gates.

## Scope

- Optimize `GET /internal/v1/talent-demand-reports` in `nexus-api/nexus_api/api/internal/assets.py`.
- Add focused read-path regression coverage in `nexus-api/tests`.
- Record query count, result parity, and timing on the same development data.

## Out Of Scope

- Schema changes, catalog-wide query changes, frontend redesign, governance writes, and preview/chunk retrieval.

## Forbidden Changes

- Do not add reverse pointers to asset or version, change governance input/target, bypass visibility, or change identity edit permissions and audit behavior.
- Do not add enterprise IAM, a custom LLM gateway, or P1/P2 features.

## Deliverables And Acceptance

- The endpoint keeps the same response fields and pagination totals.
- Latest official classification and selected generated ref remain authoritative, including superseded versions and governance decisions.
- Query count stays bounded by a constant for a page; compare response rows and latency with the pre-change implementation.
- Run focused tests and `git diff --check`; API Contract and Acceptance Review Gates require human review before merge.

## Verification Evidence

- On the same development PostgreSQL data, both implementations returned the same 20 first-page rows and total 25. The previous path issued 10 SQL statements in 352.5 ms; the optimized path issued 7 in 91.3 ms. These are single read-only server-side measurements, not browser or P95 timings.
- Direct service tests cover response parity, query bound, and latest official classification. The full API test file stalls inside TestClient in this environment; this remains a verification limitation.
- Focused direct service tests: 2 passed. Existing Crawler Console component tests: 2 passed. `git diff --check` passed.
