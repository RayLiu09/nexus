# Task Package: Teaching Standard Business Views

## Status

Complete.

## Source Context

- `AGENTS.md`: internal Console APIs stay behind `nexus-api`, mutations are
  auditable, and domain state changes require explicit Review Gates.
- `ARCHITECT.md`: `teaching_standard_library` owns the professional standard
  identity and lifecycle; `teaching_standard_course` owns standard-local course
  facts and does not duplicate major identity fields.
- `SPEC.md`: the Asset Center is a business-task view while `/assets` remains
  the technical asset ledger.
- Prototype v2.2: business lists use dense tables, detail drawers preserve list
  context, and high-risk activation requires confirmation.
- IA-1 task package: professional teaching standards and the standard course
  library are independent resource entries over the same parent/course
  projection.

## Goal

Replace the placeholder shells for professional teaching standards and the
standard course library with usable business list views backed by real domain
records. Let business experts review and correct suggested course hours, inspect
derivation evidence, and explicitly activate a complete professional standard
without adding a course-level review state.

## Frozen API Contract

All endpoints are authenticated Console-control reads or mutations under
`/internal/v1`; this task adds no `/open/v1` API.

```text
GET   /teaching-standard-libraries
GET   /teaching-standard-courses
PATCH /teaching-standard-courses/{course_id}
POST  /teaching-standard-libraries/{library_id}/activate
```

- Both list endpoints use `page` and `pageSize` and return the standard NEXUS
  list envelope with `meta.total`.
- Teaching-standard filters: `major_code`, `major_name`, `education_level`, and
  `status` (`review`, `active`, or `superseded`).
- Course filters: `library_id`, `course_name`, `major_code`, `major_name`,
  `education_level`, and `course_type` (`foundation`, `core`, or `extension`).
- Course responses join their parent library to expose major identity and
  effective library status. These fields are not copied into the course table.
- The course patch whitelist is exactly `suggested_total_hours`,
  `suggested_practice_hours`, and `suggested_hours_range`. Hour values are
  nullable non-negative integers. A non-null range is
  `{min: integer, max: integer, unit: "学时"}` and requires `min <= max`.
- Activation is an idempotent `review -> active` transition on
  `teaching_standard_library`. Repeating activation of an active library
  succeeds without another state change. A superseded library returns conflict.
- The professional graph continues to come from the existing
  `teaching_standard` capability-graph staging APIs keyed by the library's
  `normalized_ref_id`. Its frozen topology is `专业 -> 职业领域 -> 典型工作任务 /
  主要教学内容与要求`. Inferred course tags are not graph facts and must never
  be projected into nodes or edges.

## Frozen UI Contract

- `/asset-center/major/teaching-standards` renders a paginated list with:
  professional code, professional name, major category with code, major class
  with code, education level, basic study years, and actions.
- Teaching-standard row actions are `课程库` and `职业领域图谱`. `课程库` opens
  the course-library view filtered by `library_id`; `职业领域图谱` opens a right
  drawer in the business view and keeps the list context. The Drawer reuses the
  existing `资产详情 -> 知识块` professional teaching graph and its staging data;
  it does not deep-link back to the technical asset ledger. The Drawer omits
  the redundant topology caption and build-status tag, while retaining graph
  data, download, fullscreen, and node-detail actions. The shared capability
  graph does not expose an edge-label checkbox.
- `/asset-center/major/standard-course-library` renders a paginated expandable
  table. The outer row contains course ID/name, parent major code/name and
  education level, course type, suggested total/practice hours, editable hour
  range, and actions. Its page header provides `返回专业标准库`, linking directly
  to `/asset-center/major/teaching-standards`.
- Expanded course detail contains typical work task, teaching content and
  requirement, plus knowledge, skill, tool, and literacy tags.
- Suggested total hours, practice hours, and range endpoints use `InputNumber`
  controls directly in the row. `更新` persists only that row.
- `血缘追溯` opens a right Drawer showing setting basis, matched keywords,
  matched text, source standard/section/page, and every evidence binding with
  block IDs and locator. Its summary table uses a compact fixed-width label
  column so labels do not wrap character by character or create tall rows. The
  Drawer must use current Ant Design APIs without browser deprecation warnings.
- Course-row `激活` means activate the owning professional standard and all its
  course records. The confirmation text must state that scope. It is disabled
  when the parent is already active or superseded.

## Scope

- Add the four frozen teaching-standard/course endpoints, schemas/serialization, validation,
  audit writes, and focused API tests.
- Add audit event enum values and one forward-only PostgreSQL enum migration for
  course-hour updates and library activation.
- Add explicit Next.js proxy routes for browser-side list reads and mutations.
- Add both Asset Center business list components, graph/evidence drawers,
  loading/error/empty/pagination states, and focused component/E2E tests.
- Update `ARCHITECT.md`, `SPEC.md`, `readme.md`, and Prototype v2.2.

## Out Of Scope

- Search/Open API exposure, export, batch editing, bulk activation, column
  personalization, or persisted statistics.
- Editing extracted course names, course types, tags, narrative fields, major
  identity, or source evidence.
- Teaching-standard detail pages, supersession UI, version comparison, or a
  generic graph-management interface.
- Regenerating course suggestions with LLM or modifying Prompt profiles.
- Mobile-client adaptation.

## Forbidden Changes

- Do not add `status`, `review_status`, `need_confirm`, or confidence columns to
  `teaching_standard_course`.
- Do not copy `major_code`, `major_name`, or `education_level` into the course
  table; always join `teaching_standard_library`.
- Do not change the existing `library_id + course_type +
  standard_course_name` uniqueness constraint.
- Do not create a second graph projection, project inferred course tags into
  graph facts, or introduce a generic `catalog_mode`.
- Do not mutate normalized documents, governance results, source evidence, or
  asset-version lifecycle while editing course-hour suggestions.

## Deliverables

- Backend API module, audit enum migration, and API tests.
- Console proxies, types, two list views, two drawers, and frontend tests.
- Updated architecture/product/prototype contracts and Review Gate evidence.

## Acceptance

- The 20 existing teaching standards and 537 existing course rows are available
  through server-side pagination with no frontend N+1 requests.
- Every requested teaching-standard and course column is visible, with missing
  source values represented as `-` rather than invented data.
- Expanding a course row renders all six requested detail dimensions.
- Updating the three hour fields persists valid numeric values, rejects invalid
  ranges, preserves all non-whitelisted fields, and writes an audit snapshot.
- Activating a review library is confirmed, auditable, and visible for every
  course row through the parent status; no course-level status exists.
- The evidence Drawer exposes existing basis/match/source/binding provenance.
- The graph Drawer hosts the migrated `teaching_standard` knowledge view without
  navigating back to the technical asset ledger or treating inferred tags as
  graph facts.
- Backend tests, frontend typecheck/Vitest/ESLint/build, desktop Playwright
  screenshots, migration review, and `git diff --check` pass.

## Review Gates

- **Data Model Gate**: only new audit enum values are migrated; no domain table
  or relationship field changes.
- **API Contract Gate**: pagination, filter semantics, validation, idempotent
  activation, errors, and frontend mappings match this task package.
- **Permission And Audit Gate**: parent JWT protection applies before every
  read/mutation; course updates and activation record actor, trace ID, target,
  and bounded before/after summaries.
- **Version State Gate**: activation changes only the domain-library state and
  does not alter `asset_version` or `governance_result` status.
- **Frontend UX Gate**: both dense list workflows, direct numeric editing,
  confirmation, graph/evidence drawers, error/empty/loading states, and desktop layout are
  coherent and use real data.
- **Acceptance Gate**: implementation, tests, documentation, and screenshots
  agree with the frozen contract and contain no out-of-scope model changes.

## Verification Evidence

- Data Model Gate: only `TeachingStandardCourseUpdated` and
  `TeachingStandardLibraryActivated` were added to the audit enum; Alembic has
  the single `20260907_0100` head and the local PostgreSQL upgrade completed.
- API Contract Gate: four internal endpoints implement both paginated lists,
  review-only numeric updates, and idempotent whole-library activation. Six
  focused API tests pass, including a constant two-statement course-list query.
- Permission And Audit Gate: the parent internal JWT dependency protects every
  route; update and first activation write actor, trace, target, and bounded
  before/after or state summaries.
- Version State Gate: no course status was added. `review -> active` changes
  only `teaching_standard_library`; active and superseded courses reject direct
  edits.
- Frontend UX Gate: four focused Vitest cases pass for identity fields, graph
  handoff, nested details, evidence, numeric update, and activation scope.
  Desktop Playwright passed both real-data routes and verifies the professional
  graph canvas is visible and nonblank. Leaf labels are hover/click based to
  prevent overlap without changing nodes or edges.
- Acceptance Gate: the development database exposes 20 standards and 537
  courses. TypeScript, scoped ESLint, `git diff --check`, API tests, component
  tests, and desktop real-data Playwright passed. Build and final regression
  evidence are recorded in the implementation handoff.
