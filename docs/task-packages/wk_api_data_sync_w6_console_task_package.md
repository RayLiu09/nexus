# Task Package: API Data Sync W6 Console

## Goal

Expose the file-backed Provider Catalog and immutable sync plans in the current administrator Console, with manual runs and synchronous run controls.

## Scope

- Read-only Provider cards with safe metadata and generated default logos.
- Adapter-schema plan creation with five frequencies; plan pause, resume, and soft delete.
- Plan-level run drawer with progress, failure summary, manual creation, pause, resume, cancel, and refresh.
- API Push is available only from the first-level Console navigation; the legacy Data Sources card/list/create flow is retired.
- Same-origin authenticated proxy for the existing `/internal/v1/data-sync` API.
- Route the Data Sources "API 推送" card and old `?type=webhook` links to `/data-sync`; exclude legacy Webhook rows from the Data Sources list and retire the old Webhook creation option.

## Forbidden Changes

- No Provider editor, credential field, adapter protocol editor, or plan content editor.
- No result processing, new backend state, or asynchronous control queue.
- No dependency on the legacy `data_source` API.

## Review Gates

- API Contract, Permission And Audit, and P0 Frontend UX review before merge.

## Verification Evidence

- `npm run typecheck` and focused ESLint passed.
- `npm run build` passed, including `/data-sync` and `/api/data-sync/[...path]` routes. The sandboxed build could not fetch Google fonts; the allowed network build passed.
- P0 Frontend UX Review Gate remains pending human review. W7 detailed log search is outside this package.
- Data Sources entry migration: TypeScript and focused ESLint passed; legacy Webhook detail records remain intact and are no longer listed or creatable through the Console.
