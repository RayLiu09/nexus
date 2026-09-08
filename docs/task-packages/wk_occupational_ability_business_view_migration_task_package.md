# Task Package: Occupational Ability Business View Migration

## Status

Complete.

## Source Context

- `AGENTS.md`: business-task views belong in the Asset Center, internal API
  changes require contract review, and the technical asset ledger must not
  duplicate migrated domain views.
- `SPEC.md`: `competency_analysis` belongs to the professional-data domain.
- Prototype v2.2: Asset Center resources open their business view directly;
  dense lists and right Drawers preserve the list context.
- Existing Pipeline B ability-analysis contract: analyses own PGSD tasks,
  work contents, ability items, and an `ability_analysis` staging graph.

## Goal

Replace the placeholder at `/asset-center/major/occupation-analyses` with a
paginated occupational-ability analysis list. Move the existing ability-item,
tree, and graph views out of asset detail and make each available from the
corresponding list row.

## Frozen API Contract

- Reuse `GET /internal/v1/record-assets/ability-analyses` with `major_name`,
  `page`, and `pageSize`.
- Each analysis list/detail row additionally exposes four exact counts derived
  from `occupational_ability_item.ability_major_category_code` in one grouped
  query: `general_ability_count` (G), `development_ability_count` (D),
  `occupational_ability_count` (P), and `social_ability_count` (S).
- Reuse paginated `GET
  /internal/v1/record-assets/ability-analyses/{analysis_id}/ability-items` and
  `.../{analysis_id}/tasks`. No mutation or `/open/v1` behavior changes.
- The ability-item Drawer uses real server pagination and `meta.total`; it does
  not load all ability items before paginating.
- Tree construction retrieves every task and ability item in bounded pages of
  no more than 200 records.

## Frozen UI Contract

- The resource is named `职业能力分析` and uses a dense list with professional
  name, analysis model, typical-task count, general/development/occupational/
  social ability counts, and actions.
- Row actions are `能力条目`, `能力树`, and `能力图谱`; each opens a right Drawer
  without leaving the analysis list.
- The ability-item table has exactly three business columns: category, ability
  description, and corresponding task name.
- The ability tree preserves the existing task -> work content -> P-ability
  hierarchy and task-level G/S/D groups.
- The graph reuses the existing `CapabilityGraphView` with
  `buildType="ability_analysis"` and the row's `normalized_ref_id`.
- `competency_analysis` asset detail does not expose the migrated
  `结构化图谱` tab.

## Scope

- Add batched category-count projection to the internal analysis list/detail.
- Add focused internal API tests for count correctness and bounded query count.
- Add the Asset Center list and three Drawer views with loading, error, empty,
  filter, and pagination states.
- Remove the old asset-detail ability-analysis view and dispatcher branch.
- Add component and desktop E2E coverage.
- Update `SPEC.md`, `readme.md`, and Prototype v2.2.

## Out Of Scope

- Data-model migrations, new analysis models, re-extraction, graph rebuilds,
  record editing, export, bulk operations, or statistics cards.
- Changes to `/open/v1`, governance classification, asset lifecycle, or role
  permissions.
- Mobile adaptation.

## Forbidden Changes

- Do not persist redundant category-count columns on the analysis table.
- Do not issue one category-count or task request per analysis row.
- Do not rebuild or reinterpret graph facts in the browser.
- Do not include unrelated user files or broad Markdown formatting changes.

## Deliverables

- Internal list count projection and tests.
- Asset Center analysis table and three migrated Drawer views.
- Asset-detail cleanup, component/E2E tests, and updated contracts.

## Acceptance

- The analysis list displays all eight requested business columns and three
  row actions using real data.
- Category counts equal the underlying P/G/S/D ability-item rows and add no
  N+1 query behavior.
- Ability-item page changes issue the requested backend page/pageSize and show
  only category, description, and task name.
- Tree and graph Drawers preserve the existing structures and render complete,
  nonblank data where available.
- Ability-analysis asset detail shows neither the migrated views nor the
  `结构化图谱` tab.
- Backend tests, frontend component tests, TypeScript, scoped ESLint, production
  build, desktop Playwright, and `git diff --check` pass.

## Review Gates

- **API Contract Gate**: additive internal count fields, pagination semantics,
  and query bounds match this package; `/open/v1` is unchanged.
- **Frontend UX Gate**: the dense list and three Drawers are usable without
  duplicate asset-detail entry points or page-level overflow.
- **Acceptance Gate**: implementation, tests, real-data verification, and
  documentation agree with this frozen scope.

## Verification Evidence

- API Contract Gate: seven focused API tests pass. The list returns exact
  P/G/S/D counts and the no-include request remains fixed at three SELECTs
  (total, page rows, and one grouped category-count query), independent of row
  count. `/open/v1` and the database schema are unchanged.
- Frontend UX Gate: three focused component tests cover all requested columns
  and actions, the exact three-column ability-item Drawer, page-two backend
  parameters, the complete tree loader, and graph identity. The old
  asset-detail wrapper and dispatcher branch are removed, and ability-analysis
  details hide `结构化图谱`.
- Acceptance Gate: TypeScript, scoped ESLint, scoped Prettier, Python syntax,
  production build, and `git diff --check` pass. Real Chromium desktop E2E
  verifies five numeric statistic cells, all three Drawers, a nonblank graph
  canvas, no Ant Design warnings, and no page-level horizontal overflow.
  After removing a stale pre-change API process, the development response
  returned real counts G=15, D=12, P=69, and S=17 and the page displayed them.
- Full Console Vitest regression currently reports 244 passing and one
  unrelated baseline failure: `lib/status.test.ts` still expects 29 status
  definitions while the existing registry contains 35. The focused tests for
  this package all pass.
