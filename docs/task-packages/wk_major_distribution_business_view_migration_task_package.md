# Task Package: Major Distribution Business View Migration

## Status

Complete.

## Source Context

- `AGENTS.md`: Console business views use authenticated internal APIs, preserve
  audit coverage for mutations, and keep externally consumed APIs in
  `nexus-api`.
- `SPEC.md`: the Asset Center hosts business-task views while `/assets` remains
  the complete technical asset ledger.
- Prototype v2.2: professional distribution is a record-oriented resource with
  no cross-record asset boundary; resource links open their business view
  directly without an intermediate domain page.
- Existing Pipeline B contract: professional distribution records are exposed
  through the cross-dataset internal list API and retain dataset/ref lineage.

## Goal

Move the professional-distribution list workflow from the technical asset
detail into `/asset-center/major/distributions`, where users can browse,
filter, edit, and delete records across all professional-distribution datasets.

## Frozen Contract

- Reuse `GET /internal/v1/record-assets/major-distribution-records` with
  server-side pagination and its existing `year`, `province_name`,
  `major_name`, `major_code`, `education_level`, and `region_scope` filters.
- Reuse the existing audited `PATCH` and `DELETE` record endpoints through the
  current Console proxy routes. No API request or response schema changes.
- The business table displays year, province, professional name/code,
  education level, region scope, distribution count, and edit/delete actions.
- `/assets/{asset_id}` no longer mounts the professional-distribution business
  list and does not expose the `结构化图谱` tab for this record type.

## Scope

- Add an Asset Center professional-distribution table component and route
  branch backed by the cross-dataset API.
- Preserve filtering, pagination, editing, deletion, loading, error, and empty
  states.
- Remove the professional-distribution business component from asset detail.
- Add focused component and desktop E2E coverage.
- Update `SPEC.md`, `readme.md`, and Prototype v2.2 for the moved ownership.

## Out Of Scope

- New aggregation cards, charts, imports, exports, batch mutations, or a
  professional-domain summary page.
- Changes to the professional-distribution schema, governance classification,
  Pipeline B normalization, or `/open/v1` APIs.
- Mobile adaptation or role/permission redesign.

## Forbidden Changes

- Do not reintroduce an asset boundary for cross-dataset professional-
  distribution browsing.
- Do not duplicate the existing read/mutation API or bypass mutation audit.
- Do not change normalized references, governance results, or asset-version
  lifecycle state from the business list.
- Do not include unrelated user files or broad Markdown formatting changes.

## Deliverables

- Asset Center route and professional-distribution table.
- Asset-detail dispatcher cleanup.
- Frontend tests and updated product/prototype documentation.

## Acceptance

- `/asset-center/major/distributions` shows real cross-dataset records with
  server-side filtering and pagination.
- Editing and deleting use the existing audited endpoints and refresh the list.
- Professional-distribution asset detail shows neither the `专业布点列表`
  business view nor the `结构化图谱` tab.
- Component tests, frontend typecheck, scoped lint, desktop Playwright, and
  `git diff --check` pass without new Ant Design console warnings or page-level
  horizontal overflow.

## Review Gates

- **API Contract Gate**: no API change; existing list, patch, and delete
  contracts are reused.
- **Permission And Audit Gate**: authenticated internal routes remain in use;
  record mutations retain their existing audit events.
- **Frontend UX Gate**: the dense cross-dataset list, filters, confirmation,
  failures, empty state, and desktop layout are coherent.
- **Acceptance Gate**: code, tests, documentation, and real-data verification
  agree with the frozen migration scope.

## Verification Evidence

- API Contract Gate: the Asset Center server route reads the existing
  cross-dataset internal endpoint in one paginated request; no backend or
  `/open/v1` contract changed.
- Permission And Audit Gate: browser mutations continue through the existing
  authenticated Console proxies to the audited record patch/delete handlers.
- Frontend UX Gate: URL-backed filters, explicit reset, server pagination,
  dense record columns, edit modal, delete confirmation, API error state, and
  empty state are covered. Real Chromium verification found no Ant Design
  warning or page-level horizontal overflow.
- Acceptance Gate: seven focused Asset Center component tests, TypeScript,
  scoped ESLint, production build, and all eight Asset Center Chromium desktop
  E2E tests pass. A real professional-distribution asset confirms that its
  technical detail has neither `专业布点列表` nor a `结构化图谱` tab.
