# Task Package: Course Textbook Business View

## Status

Complete.

## Source Context

- `AGENTS.md`, `ARCHITECT.md`, `SPEC.md`, and `WORKFLOWS.md`: architecture,
  API, UI, and Review Gate boundaries.
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: Asset Center IA
  and list/Drawer interaction baseline.
- `docs/task-packages/wk_business_asset_center_ia1_task_package.md`: fixed
  five-domain Asset Center and direct resource-entry contract.
- `docs/task-packages/wk_conceptual_textbook_knowledge_outline_v1_task_package.md`
  and `wk_pipeline_owned_knowledge_outline_build_task_package.md`: persisted
  theory/hybrid knowledge-outline ownership and eligibility.
- Course-textbook Task Outline task packages: persisted training-operation
  outline and existing Console tree/radial views.

## Goal

Merge the former theory-textbook and training-textbook Asset Center entries
into one `课程教材` business list, and move the textbook-specific outline views
from technical asset detail into conditional row actions in that list.

## Frozen Contract

- Route: `/asset-center/teaching-resources/course-textbooks`.
- This is a fixed business entry backed by the `course_textbook` domain table.
  Migration `0101` renames the former `task_outline_profile` table in place,
  preserving identifiers and existing projections. It does not rename the
  `course_textbook` governance classification or add a persisted catalog mode.
- Type mapping is fixed:
  - `theory_knowledge` and `hybrid` -> `theory` / `理论型`.
  - `training_operation` -> `training` / `实训型`.
- The list reads only the current catalog-visible asset version and latest
  generated normalized ref (`available` or `review_required`). Historical,
  archived, disabled, failed, superseded-version, and superseded-ref profiles
  do not enter the list or Asset Center count.
- List fields are textbook name, type, publisher, chief editor, and publication
  year. Bibliographic values come only from normalized-ref/document metadata;
  missing values display `-`. Explicit publisher, chief-editor, publication-
  date, and edition cover lines may populate that metadata during normalize;
  non-published materials remain empty. The title uses the textbook/asset title
  as the stable source and removes an explicit numeric sequence prefix and
  terminal document file extensions for display.
- `document_metadata.chief_editors` is preferred when present; legacy
  `document_metadata.authors` is a compatibility fallback. Publication year is
  the first valid four-digit year in `publish_date`.
- The internal list API supports server-side pagination and filters for title,
  type, publisher, chief editor, and publication year. It must not load outline
  nodes or execute per-row queries.

## Interaction Contract

- Theory rows expose `知识大纲径向图` and `知识大纲树`. The latter remains a
  true Left-to-Right orthogonal ECharts layout; the layout direction is not
  repeated in the user-facing action or Drawer title.
- Training rows expose `任务大纲树视图` and `任务大纲圆形树`.
- Each action opens a right-side Drawer and keeps the list context. Only the
  selected row/view is fetched after opening; list rendering preloads no
  outline payloads.
- The knowledge radial graph, task tree, and task radial graph preserve the
  existing Asset Detail functionality, including graph fullscreen/download
  and knowledge-node content inspection where applicable.
- The new knowledge tree uses ECharts orthogonal layout with `orient: "LR"`;
  it is not the former indented Ant Design tree.
- A row action locks the selected view. The Drawer does not repeat a mode
  switch or expose the technical `重建` operation.
- Outline Drawers do not render profile subtype, graph-admission, node-count,
  depth, fallback, or projected-chunk summary badges above the view. Viewport
  actions, empty/error states, fullscreen, and download remain available.
- After migration, textbook-specific knowledge/task outline choices and their
  eager Task Outline request are removed from technical Asset Detail. Generic
  RAG and eligible Evidence Graph views remain unchanged.
- Desktop is the acceptance target; no mobile-specific adaptation is added.

## Scope

- Replace the two teaching-resource catalog entries and count keys with one
  `课程教材` entry.
- Rename the persisted course-textbook master projection in place and add one
  authenticated internal paginated list API.
- Improve normalized document bibliographic extraction for explicit textbook
  cover metadata without fabricating values for unpublished material.
- Add a bounded, idempotent backfill for existing `course_textbook` refs. It
  reads normalized-document payloads only, fills missing bibliographic fields,
  and never overwrites existing values or mutates normalized objects.
- Add the course-textbook list, filters, conditional row actions, and Drawer.
- Move/refactor the two outline components into business/shared ownership and
  add the Left-to-Right knowledge tree mode.
- Remove textbook outline UI and Task Outline data plumbing from Asset Detail.
- Add focused backend/frontend tests and update architecture/product/prototype
  contracts.

## Out Of Scope

- A new table or destructive rebuild of the existing textbook projection.
- Re-governance, unbounded cross-classification metadata backfill, or a new
  bibliographic LLM call.
- Editing textbook metadata or outline nodes.
- Public/Open API, query/search behavior, or index pipeline changes.
- Case library, course-standard library, textbook detail page, role, or
  permission redesign.

## Forbidden Changes

- Do not read raw files, raw JSON, or MinerU raw output from the list API.
- Do not infer or fabricate missing publisher, editor, or year values.
- Do not make a list request per textbook or load all outline nodes with the
  list.
- Do not keep duplicate textbook outline entry points in Asset Detail.
- Do not add a new textbook classification or split `hybrid` into a third
  display type.
- Do not change knowledge/task outline node persistence, extraction,
  governance, indexing, or audit semantics beyond the master-table rename.

## Acceptance

- Asset Center shows exactly one `课程教材` subtype and no `理论教材` or
  `实训教材` subtype; its count matches the list total under the frozen current
  read model.
- The list presents the five frozen business columns with server pagination and
  truthful missing-value states.
- Theory and training rows expose only their respective two actions.
- Opening an action fetches only that row's matching outline. The knowledge-tree
  action renders an ECharts tree with `layout: "orthogonal"` and `orient: "LR"`
  without showing the implementation direction in its label.
- Migrated graph canvases are nonblank in desktop Playwright acceptance, and
  Drawer open/close produces no React or Ant Design console warning.
- Asset Detail makes no Task Outline request and exposes no knowledge/task
  outline mode for course textbooks.
- The list endpoint has a bounded statement count independent of page size and
  does not select `task_outline_node` or `knowledge_outline_node`.
- Focused backend tests, frontend tests, typecheck, scoped lint, production
  build, real-data acceptance, and `git diff --check` pass.

## Review Gates

- **API Contract Gate**: type mapping, current visibility, metadata fallback,
  pagination/filter semantics, and bounded query count are covered by tests.
- **Data Model Gate**: the in-place table rename preserves course-textbook IDs,
  normalized-ref/version references, uniqueness, task-node foreign keys, and a
  reversible downgrade; no redundant reverse pointer is introduced.
- **Frontend UX Gate**: dense list, conditional actions, Drawer sizing, locked
  views, nonblank graphs, and warning-free interaction pass desktop review.
- **Retirement Gate**: Asset Detail no longer imports, renders, or eagerly loads
  textbook outline data.
- **Acceptance Gate**: implementation, documentation, Asset Center count, and
  real list total agree.

## Verification Evidence

- Alembic migration `20260909_0101` renamed `task_outline_profile` to
  `course_textbook` in place. All 7 rows and their identifiers were preserved,
  and `task_outline_node.profile_id` now references `course_textbook.id`.
- The metadata backfill scanned 7 current textbook projections, updated 2 from
  explicit normalized-document publication evidence, left 5 without evidence
  empty, and reported 0 updates on a second dry run.
- Focused domain/metadata/persistence tests passed (40), the broader outline
  suite passed (122), and focused API tests passed (25).
- Focused Console tests passed (13 plus 5 Drawer cases), TypeScript and scoped
  ESLint passed, and the Next.js production build completed successfully.
- Desktop Playwright acceptance passed against 7 real rows and opened all four
  Drawers without Ant Design warnings. It verified cleaned file extensions,
  no top summary badges, no user-facing `Left-to-Right` suffix, and the retained
  Left-to-Right orthogonal knowledge-tree layout.
- `git diff --check` passed. `nexus-api` health returned HTTP 200 and the
  restarted `nexus-console` course-textbook route returned its expected login
  redirect.
