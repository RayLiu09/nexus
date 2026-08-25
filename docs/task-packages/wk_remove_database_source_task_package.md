# Task Package: Remove Database Direct Source

## Goal

Remove the direct `database` data-source connector. NEXUS continues to use
PostgreSQL as its own control-plane storage, but no longer accepts, displays,
or scans external database connections as ingestion sources.

## Scope

- `DataSourceType`, connection config schemas, scan/routing logic, and its
  PostgreSQL enum migration.
- Internal data-source API validation, Console data-source views, and mock data.
- Focused tests and current architecture/product documentation.

## Out Of Scope

- NEXUS PostgreSQL runtime configuration, metadata storage, or search storage.
- Deleting or rewriting historical assets.
- Adding a replacement connector.

## Acceptance

- `source_type=database` is rejected at the API schema boundary.
- New installs and upgraded PostgreSQL schemas no longer expose `database` in
  `datasourcetype`; migration aborts with a clear error if legacy rows exist.
- Console has no database connector card, creation form, or detail editor.
- NAS, Crawler, Webhook, and file-upload paths retain their existing behavior.
