# Task Package: Asset Manual Retirement

## Goal

Allow business experts to manually retire or permanently delete an unsuitable
asset from the asset detail page. Archive retains lineage; deletion removes
the asset's data and derivatives while retaining only a minimal audit record.

## Source Context

- `ARCHITECT.md` and `AGENTS.md`: asset/version state is a derived read model;
  no current-version reverse pointer may be introduced.
- `docs/企业数据与知识资产平台中间件调用契约v1.0.md`: an asset's lifecycle
  must be represented in PostgreSQL; deleting object storage is not a valid
  way to express asset disablement or archival.
- `WORKFLOWS.md`: this is a data-model lifecycle and internal API contract
  change, requiring Data Model, API Contract, Permission And Audit, and
  Frontend UX review evidence.

## Scope

- Internal asset lifecycle operations and their Console proxy routes.
- Asset detail header actions for archive and irreversible deletion.
- Asset/version and derived-data cleanup, audit events, role authorization,
  storage reference safety, and focused regression tests.

## Out Of Scope

- Restoring an archived or deleted asset, bulk actions, or public `/open` API
  write endpoints.

## Frozen Contract

- `POST /internal/v1/assets/{asset_id}/archive` archives the asset and every
  version as `archived`.
- `DELETE /internal/v1/assets/{asset_id}` irreversibly removes the asset,
  versions, normalized data, index data, and related derivative rows. Its
  audit log records only a bounded identity/count snapshot and no lineage.
- Raw objects and object-storage payloads are removed only when no other
  asset version references them.
- Both actions require `Idempotency-Key` and a `business_expert` or
  `platform_data_admin` user session.
- Archive is idempotent and prevents background governance from publishing a
  manually retired version back to `available`. Delete is deliberately not
  replayable after success: a repeated request returns 404.

## Forbidden Changes

- Do not alter public asset APIs or bypass the internal JWT boundary.
- Do not add reverse pointers to `asset` or `asset_version`.

## Acceptance

- The asset detail header presents archive and delete commands. Delete uses a
  warning confirmation followed by exact asset-title entry before it is sent.
- Archive removes an asset from current/available reads and sets all versions
  to `archived`.
- Delete removes the asset and its derivatives, while retaining only the audit
  event and not deleting storage data referenced by another asset.
- Business experts and platform data admins can act; other roles receive 403.
- Repeating either operation is safe and produces no state regression.
- Asset lifecycle changes are auditable and focused backend/frontend tests
  pass.
