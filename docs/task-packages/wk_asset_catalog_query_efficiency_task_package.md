# Task Package: Asset Catalog Query Efficiency

## Source Context

- `ARCHITECT.md`: current version and current normalized reference are derived
  read models; `governance_result` targets `normalized_asset_ref`.
- `SPEC.md`: the asset catalog is an operational current-view page.
- `WORKFLOWS.md`: this is a bounded API-read performance repair with focused
  regression and query-count verification.

## Goal

Make the first asset-catalog implementation usable at the current data volume
by removing per-asset query fan-out and by applying catalog filters and
pagination in PostgreSQL.

## Scope

- `/internal/v1/assets` catalog query and its focused tests.
- Batch loading the current page's versions, normalized refs, governance
  results, and index manifests.
- SQL-side status, classification, level, and tag-ref filters plus SQL-side
  count and pagination.

## Out Of Scope

- A persisted or materialized catalog projection.
- New asset/governance columns, migrations, API schema changes, or Console UI
  changes.
- Changes to governance decisions, tags, indexing, or asset lifecycle rules.

## Forbidden Changes

- Do not add `asset.current_version_id` or any equivalent reverse pointer.
- Do not move governance authority away from `governance_result` and its
  `normalized_asset_ref` target.
- Do not weaken catalog visibility, status, or semantic-tag matching rules.

## Acceptance

- The response schema and catalog semantics remain unchanged.
- The default `status=visible` request is SQL-filtered and paginated before
  catalog-row assembly.
- Catalog query count remains bounded as the page row count grows.
- Focused catalog tests and static checks pass.
