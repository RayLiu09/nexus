# Task Package: Governance Review Queue Query Efficiency

## Source Context

- `ARCHITECT.md`: governance results are immutable snapshots anchored to
  `normalized_asset_ref`; human review reads the latest official snapshot.
- `SPEC.md`: the Console governance-review queue is an operational P0 page.
- `WORKFLOWS.md`: this is a bounded internal API and Console performance fix.

## Goal

Make the governance-review queue usable at current data volume by moving
latest-result selection, pending filtering, counting, and pagination into SQL;
remove per-row relation loads; and avoid materializing queue rows for a
navigation badge count.

## Scope

- `/internal/v1/governance-reviews/pending` and a count-only internal route.
- Console navigation badge call site.
- Focused governance-review queue tests.

## Out Of Scope

- Persisted projections, data-model migrations, governance decision changes,
  audit changes, review UI redesign, and external APIs.

## Forbidden Changes

- Do not change the latest-snapshot semantics: a historical review-required
  result is hidden when a newer official result exists for the same ref.
- Do not add current-result reverse pointers or move governance ownership away
  from `governance_result` and `normalized_asset_ref`.
- Do not weaken the existing internal authentication boundary.

## Acceptance

- Queue response shape and review semantics remain unchanged.
- Latest-result selection, count, sorting, and pagination run in SQL.
- Queue row relation loading remains bounded as page size grows.
- Navigation badge uses a count-only API path.
- Focused API tests and query-count regression pass.
