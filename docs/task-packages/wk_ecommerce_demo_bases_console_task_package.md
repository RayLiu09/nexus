# Task Package: 电商示范基地应用层与 Console 双视图

## Source And Goal

- User authorizes implementing the existing design over `ecommerce_parks`:
  Asset Center → 市场数据 → 电商示范基地 → 国家 / 省份.
- `ARCHITECT.md`, `SPEC.md`, Prototype v2.2 and `WORKFLOWS.md` remain binding.
- The earlier design package owns the completed source/model work. This slice
  owns database reads, authenticated internal APIs and the two Console views.
- Single-agent implementation; no parallel-agent contract is required.

## Scope And Frozen Contract

- `GET /internal/v1/ecommerce-demo-bases`: typed, paginated database reads.
- `GET /internal/v1/ecommerce-demo-bases/aggregate`: matching totals, national
  batch/province counts and level-wide database filter options.
- Both accept `level=national|provincial`, literal name `q`, `province_code`
  and `recognized_year`. `batch=first|second|supplement` is national-only;
  a provincial batch request is 422. Page/pageSize follow existing bounds.
- Existing fixed counts UNION adds `market/ecommerce-demo-bases`; no extra
  overview request. All counts are actual domain rows, not declared totals.
- `/asset-center/market/ecommerce-demo-bases`: 国家 / 省份 tabs, national
  batch selection, column chart and province choropleth, paginated read-only
  lists. Filters/page state live in the URL. Province identity comes from
  persisted collection metadata, never a title inference.
- Public static GeoJSON ships with the app; record reads do not access source
  JSON files or upstream websites. Sources use fixed validated Ministry URLs.
- National chart/map, count and list share submitted filters; drafts do not
  alter pagination until 检索. Failed reads never appear as successful zeroes.

## Ownership

- API schemas, ecommerce internal router and registration, counts UNION/tests.
- Console catalog, API types, resource page branch, dedicated view/charts,
  static map, unit/route/E2E tests.
- This package, design, root contracts, Prototype and review evidence.

## Forbidden / Out Of Scope

- No database/model migration or record mutation, CRUD, import/export UI,
  scheduler, online source sync, AI calls, asset/governance or semantic index.
- No IAM/gateway/infrastructure changes or unrelated worktree changes.
- No inferred address, coordinate, missing-base facts or invented metrics.

## Acceptance And Review

- API: auth, GET-only methods, escaped literal search, filter intersections,
  stable pagination, matching aggregates, independent filter options, source
  flag and URL allowlist; actual 170/142 and 34/63/73 snapshot integration.
- Console: overview link/count, URL restoration, national/province switch,
  chart/map selection and clearing, pagination preserving submitted filters,
  timezone-correct dates, empty/error states and no write controls.
- Run targeted pytest/Vitest, typecheck, changed-file lint and build. Capture
  desktop/tablet browser evidence and document environment blockers honestly.
- API Contract, Frontend UX and Acceptance review evidence is required;
  automated verification is not described as human approval. Human review
  remains pending until the concrete implementation is reviewed.
