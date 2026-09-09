# Task Package: Major Profile Business View

## Status

Complete.

## Source Context

- `AGENTS.md`, `ARCHITECT.md`, `SPEC.md`, and `WORKFLOWS.md`: normalized-input,
  Asset Center, API ownership, documentation, and Review Gate boundaries.
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: page and interaction
  baseline.
- `docs/task-packages/wk_business_asset_center_ia1_task_package.md`: fixed
  `/asset-center/major/profiles` route and business-view boundary.
- `docs/task-packages/wk_major_profile_api_console_task_package.md` and
  `wk_major_profile_multi_view_task_package.md`: existing `major_profile.v1`
  projection, multi-profile-per-ref behavior, and read APIs.

## Goal

Provide a professional-introduction business list backed by `major_profile`,
with compact identity columns and an expandable panel for the requested domain
facts, and retire the duplicate professional-profile view from technical Asset
Detail.

## Frozen Contract

- Route: `/asset-center/major/profiles`.
- One outer row represents one `major_profile` record. A normalized document
  containing multiple majors therefore contributes multiple business rows.
- The outer list shows professional name, professional code, study duration,
  education level, and institution name.
- The expanded panel shows occupation orientation, training positioning,
  ability requirements, courses and practical training, and certificates.
- The list includes only projections anchored to the current catalog-visible
  asset version and latest generated normalized ref (`available` or
  `review_required`) whose latest official classification is `major_profile` or
  the historical compatibility value `program_profile`.
- List pagination and identity filters are server-side. Child collections are
  not loaded by the list request; expanding a row lazily loads and caches that
  profile's existing detail endpoint.
- Asset Detail retains generic document knowledge chunks but no longer imports,
  requests, or renders the dedicated professional-profile directory/graph
  view.

## Scope

- Extend the existing internal major-profile list with optional institution,
  official-classification, and current-catalog visibility filters.
- Add the Asset Center professional-profile list and expandable detail panel.
- Remove the dedicated major-profile knowledge dispatcher and component from
  technical Asset Detail.
- Add focused API and Console tests and update architecture, product,
  prototype, and repository contracts.

## Out Of Scope

- Database migrations, domain-schema changes, extraction changes, re-governance,
  or historical backfill.
- Editing professional-profile fields or child records.
- Moving the retired professional graph into the Asset Center; this slice
  contains only the requested expandable business panel.
- Changing Open API behavior, semantic chunk construction, search, or indexing.
- Changing the Asset Center card count from asset count to profile-row count.

## Forbidden Changes

- Do not read raw files, raw JSON, or MinerU output.
- Do not infer missing institution, professional, or child facts in the UI.
- Do not preload child collections or issue per-row requests during list
  rendering.
- Do not reintroduce `program_profile` as a new domain model or governance code.
- Do not remove the generic document knowledge-block capability from Asset
  Detail.

## Acceptance

- The professional-profile route renders the five requested outer columns with
  server pagination and truthful `-` values for missing optional fields.
- Expanding one row loads only that profile and renders all five requested
  domain sections without adding nested tables.
- Reopening an already loaded row reuses its cached detail in the mounted list.
- Archived, disabled, failed, superseded-ref, and wrongly classified projections
  are excluded from the business list.
- Asset Detail contains no `MajorProfileKnowledgeView` import, request, or
  specialized dispatch; generic document chunks remain available.
- Focused backend/frontend tests, TypeScript, scoped lint, production build,
  `git diff --check`, and desktop visual acceptance pass.

## Review Gates

- **API Contract Gate**: default internal API behavior remains compatible; new
  filters are optional and covered by current-visibility and classification
  tests.
- **Frontend UX Gate**: dense list, readable expandable panel, loading/error/
  empty states, and desktop layout match the Asset Center baseline.
- **Retirement Gate**: technical Asset Detail no longer owns the specialized
  professional-profile presentation.
- **Acceptance Gate**: implementation, tests, task package, and root/product
  contracts agree without data-model or governance changes.

## Verification Evidence

- `nexus-api`: `env PYTHONPATH=../nexus-app:. .venv/bin/pytest tests/test_major_profile_api.py -q`
  -> 9 passed, including current-version,
  superseded-ref, official-classification, institution-filter, two-query, and
  no-child-table assertions.
- `nexus-console`: focused Vitest suite -> 3 files / 29 tests passed;
  `pnpm exec tsc --noEmit` and scoped ESLint passed.
- `nexus-console`: `pnpm build` completed successfully. The first sandboxed
  attempt could not fetch Google Fonts; the permitted network retry compiled,
  type-checked, generated static pages, and finalized routes successfully.
- Real-data Chromium desktop acceptance passed for the professional-profile
  list and Asset Detail retirement tests. The list exposed 65 current-visible
  profiles, loaded one row's five detail sections, and retained generic RAG in
  technical Asset Detail.
- Browser console sampling returned no warnings, errors, or page errors;
  document-level horizontal overflow was false. The expandable detail panel
  bounds unusually long historical projection text with local scrolling.
- `git diff --check` passed. Existing unrelated untracked reports, slides,
  reference content, and governance-review task package were left untouched.
