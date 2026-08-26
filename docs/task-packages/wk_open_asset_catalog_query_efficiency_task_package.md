# Task Package: Open Asset Catalog Query Efficiency

## Source Context

- `ARCHITECT.md`: external asset reads expose only available versions; governance
  remains anchored to `normalized_asset_ref`.
- `SPEC.md`: `GET /open/v1/assets` is a governed public catalog with a P95
  target below 200 ms.
- `WORKFLOWS.md`: this is a bounded API-read performance repair with focused
  regression and query-count verification.

## Goal

Remove the public asset catalog's per-row database fan-out and apply its
available-version, domain, tag-reference, count, and pagination operations in
SQL before public-row assembly.

## Scope

- `/open/v1/assets` implementation and focused API tests.
- Batch loading the current page's assets, generated normalized refs,
  governance results, and public tags.
- SQL-side available-version/domain/tag-reference filtering, counting, and
  pagination.

## Out Of Scope

- A persisted catalog projection, migration, response-schema change, or
  Console UI change.
- Changes to API-key authorization, public tag matching semantics, governance
  decisions, or version-state rules.

## Forbidden Changes

- Do not introduce `asset.current_version_id` or another reverse pointer.
- Do not move governance authority away from `governance_result` and its
  `normalized_asset_ref` target.
- Do not weaken the public available-version gate or exact/semantic tag
  matching behavior.

## Acceptance

- Public response schema and filtering semantics remain unchanged.
- The request is filtered and paginated in SQL before public-row assembly.
- Query count is bounded as page row count grows.
- Focused catalog tests and syntax checks pass.
