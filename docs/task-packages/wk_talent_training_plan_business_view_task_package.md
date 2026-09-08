# Task Package: Talent Training Plan Business View

## Status

Complete.

## Source Context

- `AGENTS.md`: domain projections consume `normalized_document` through
  `normalized_asset_ref`; internal Console APIs remain behind `nexus-api`.
- `ARCHITECT.md` / `SPEC.md`: the Asset Center owns business-task views while
  `/assets` remains the complete technical asset ledger.
- Prototype v2.2: business lists use dense tables and preserve list context
  when opening detail Drawers.
- `wk_talent_training_plan_task_package.md`: career orientation is controlled,
  plan-local JSON with normalized-document evidence; it does not create global
  professional, industry, occupation, position, skill, or certificate master
  data.

## Goal

Add the `/asset-center/major/training-plans` business list. The expandable list
shows plan identity in the outer table, career-orientation dimensions in a
non-table information panel, and opens the existing course-knowledge and
position-capability graphs in right-side Drawers without leaving the list.

## Frozen Interface

- Reuse `GET /internal/v1/talent-training-plans` with its existing server-side
  pagination and filters. The Asset Center passes `official_only=true`, which
  admits only rows whose latest official governance classification is
  `talent_training_plan`, and `catalog_visible_only=true`, which applies the
  same current asset/version/ref visibility read model as the Asset Center
  count. The endpoint defaults remain compatible.
- The internal list item adds `career_orientation_summary`, containing only
  `major_categories`, `major_classes`, `industries`, `occupations`, and
  `positions`. Each item contains source-backed `name` and optional `code`;
  position capability details are excluded from the list response.
- The externally consumed `/open/v1/talent-training-plans` response remains
  unchanged in this task.
- Professional category/class facts are stored inside the existing plan-local
  `career_orientation` JSON. They are extracted only from explicit normalized
  table or labelled-text evidence. They are never inferred from
  `major_profile`, course text, or another professional standard.
- Missing career dimensions are represented as empty arrays and displayed as
  `-`; no synthetic fallback value is allowed.
- `GET .../{plan_id}/course-knowledge-graph` and
  `GET .../{plan_id}/position-capability-graph` remain unchanged. A Drawer
  fetches only its selected graph after the row action is clicked.
- Talent-training-plan-specific graph choices move out of asset detail. Asset
  detail retains the generic RAG/document knowledge view.

## Scope

- Extend deterministic talent-training-plan career-orientation extraction for
  explicit professional category/class name-code values.
- Extend the internal list serializer with one bounded business summary; keep
  the list query bounded and free of per-row detail requests.
- Add the expandable Asset Center list, filters, graph Drawers, reusable graph
  renderer, and focused component/E2E coverage.
- Remove the talent-training-plan graph dispatcher and metadata plumbing from
  technical asset detail.
- After a read-only coverage check, reuse the existing idempotent, audited
  projection rebuild for refs whose latest official classification is
  `talent_training_plan`; do not rebuild excluded historical projections.
- Update architecture, product, prototype, repository overview, and focused
  tests for the changed UI/API behavior.

## Out Of Scope

- Deleting or rewriting historical rows projected under another official
  classification. The business list only excludes them from its read view.
- Creating professional taxonomy master tables or new database columns.
- Editing talent-training-plan records, lifecycle state, governance state, or
  graph facts.
- Search/retrieval redesign, role/permission design, mobile adaptation, or a
  new externally consumed API.
- Rebuilding projections whose latest official classification is not
  `talent_training_plan`.

## Forbidden Changes

- Do not read raw files, MinerU raw output, or `major_profile` as extraction
  input.
- Do not infer professional category/class from courses, positions, or another
  asset.
- Do not create global master data from plan-local career facts.
- Do not eagerly fetch both graphs for every list row.
- Do not add reverse pointers, enterprise IAM, a NEXUS LLM gateway, or a new
  AI-governance service.
- Do not run Prettier over Markdown files.

## Deliverables

- Deterministic extractor and internal API serializer changes.
- Asset Center list and lazy graph Drawer components.
- Asset-detail migration cleanup.
- Backend extractor/API tests, frontend component tests, and desktop E2E path.
- Bounded contract-document updates and verification evidence.

## Acceptance

- The outer table displays professional name/code, study duration, education
  level, institution name, and the two requested graph actions.
- The business-list total matches the Asset Center count; archived, disabled,
  failed, superseded-version, and superseded-ref projections stay auditable but
  do not enter the list.
- Expanding a row displays a non-table, two-region information panel:
  professional category/class under professional belonging, and industry,
  occupation, and position under career orientation. Position gets the widest
  content track, and source codes remain visible where present.
- Professional taxonomy values retain normalized-document evidence and remain
  empty when the source does not provide them.
- Opening one graph Drawer issues only that graph request, renders loading,
  empty/unavailable, error, and usable graph states, and preserves image
  download/fullscreen behavior.
- Asset detail no longer exposes talent-training-plan course/position graph
  choices and still exposes generic RAG chunks.
- Focused Python, Vitest, TypeScript, ESLint, production-build, and desktop
  Playwright checks pass; no residual pytest/Vitest process remains.

## Review Gates

- API Contract Gate: review the additive internal-list summary and unchanged
  Open API response.
- Frontend UX Gate: review dense table, expanded-panel readability, lazy Drawer
  states, and asset-detail migration.
- Acceptance Gate: review focused automated checks and a real-data desktop
  rendering with no Ant Design console warnings.

## Verification Evidence

- Extractor: 17 focused tests pass, including headerless key/value tables,
  `rowspan` recovery, institution-name removal, and conservative title fallback.
- API: 11 talent-training-plan tests plus the Asset Center bounded-count test
  pass. The business list remains three SQL statements and its live total is
  22, matching the Asset Center count; the six excluded official projections
  resolve to five archived versions and one failed version.
- Console: four focused Vitest cases, TypeScript, scoped ESLint, and the Next.js
  production build pass. The final desktop E2E verifies the two graph Drawers,
  removal from technical asset detail, no Ant Design warnings, and a computed
  24px left indent on the expanded information panel.
- Development rebuild: 28 latest-official normalized refs rebuilt successfully
  with extractor v1.2, 566 plan-owned courses, and 28 audit events. Current
  catalog visibility admits 22 without deleting the six historical projections.
- Real-data check: professional names containing their institution reduced from
  six to zero; generic school-type false positives, invalid category codes, and
  invalid class codes are all zero. `浙江纺织服装职业技术学院` and
  `浙江广厦职业技术学院` now retain separated professional category, class,
  industry, and occupation facts.
