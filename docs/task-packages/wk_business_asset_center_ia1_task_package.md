# Task Package: Business Asset Center IA-1

## Status

Complete. The Asset Center uses compact domain cards as the only domain-level
entry surface, links each subtype directly to its resource view, and loads real
per-resource counts without domain-summary pages or persisted statistics.

## Source Context

- `AGENTS.md`: architecture, UI, task-package, and Review Gate boundaries.
- `ARCHITECT.md`: the generic asset ledger remains the technical governance
  read model; domain projections and record reads retain their existing data
  ownership.
- `SPEC.md`: Console page scope and the distinction between internal control
  views and business-facing capabilities.
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: current Console
  navigation and page baseline, amended by this bounded IA-1 slice.
- Product decisions in this task cycle: the Asset Center is a business-task
  view, not a data-administrator-only view; role/permission design and source
  trace interactions are deferred.

## Goal

Replace the flat asset-ledger-first entry with a stable Asset Center organized
around five business domains, while retaining `/assets` as the complete
technical asset ledger. Make the frozen domains and resource routes visible and
navigable with truthful on-demand counts, without inventing domain fields or
unfinished domain models.

## Frozen Information Architecture

The first-level Console navigation is:

```text
总览
资产中心
智能检索
数据管理
治理管理
访问与审计
个人工作
```

The Asset Center contains:

```text
产业政策数据
  产业政策（全部 / 国家 / 省级 / 区域）
  教育政策（全部 / 国家 / 省级 / 区域）
  产业报告
  行业报告

专业数据
  专业简介
  专业布点数据
  专业教学标准
  标准课程库
  专业人才需求报告
  人才培养方案
  职业分析数据

市场数据
  岗位需求数据
  产业园区数据
  企业数据
  证书数据

教材资源数据
  理论教材
  实训教材
  教学案例
  课程标准

用户行为数据
  能力指标库
  评分体系库
  学习数据
  学情分析
```

- Policy level is a page-local business filter, not six combined
  classification codes.
- `education_policy` is a future governance classification task and is not
  added to the governance rules in IA-1.
- Industrial parks and enterprises use future fixed-schema bulk imports from
  their own list pages. IA-1 introduces neither `industrial_park` nor
  `enterprise` classifications.
- The future industry-data domain model has no `产业画像` Asset Center entry.
- `标准课程库` is an independent Asset Center business entry backed by
  `teaching_standard_course` records. It is not a new governance
  classification or a copied course table.

## Scope

- Create a centralized, compile-time Asset Center domain and route registry.
- Add `/asset-center` and every frozen resource route shell. Domain-only paths
  such as `/asset-center/policy` do not provide an intermediate summary page.
- Show a real count for every resource from one Asset Center aggregate request.
  Asset-bounded resources count catalog-visible assets; record/library
  resources count their domain rows. Missing future models return zero.
- Keep `智能检索` as one direct first-level route to `/query`. The retired
  `/retrieval-test` route redirects to `/query` and has no navigation entry.
- Replace the static six-domain `/data-assets` mock board with a redirect to
  `/asset-center`, and remove its mock counts/components.
- Reorganize the global sidebar into the seven frozen first-level groups.
- Rename `/assets` in navigation and page copy to `全部资产台账` without changing
  its API, filters, table, detail routes, or lifecycle behavior.
- Add Asset Center-aware breadcrumbs.
- Add focused unit/E2E coverage for the registry, navigation, route validation,
  and primary responsive page.
- Update architecture, product, prototype, and repository overview contracts.

## Out Of Scope

- Role design, permission changes, route guards, or data-scope policy.
- Mobile navigation and mobile-specific layout adaptation; the platform has no
  mobile-client requirement.
- Asset/source lineage fields or links in Asset Center business views.
- Any new business-facing `/v1` or `/open/v1` API. IA-1 adds only one internal
  Console aggregate read.
- Domain-specific list columns, filters, sorting, charts, trend metrics, or
  final empty-state copy.
- Persisted Asset Center counts or a statistics read model; IA-1 uses an
  on-demand aggregate read only.
- Industry-profile navigation, industry domain schemas, extraction, or
  backfill.
- Education-policy governance rules or historical re-governance.
- Industrial-park/enterprise schemas, imports, classifications, or storage.
- Professional teaching-standard detail layout, review UI, activation, or
  supersession.
- Course-library list/detail, certificate-library, case-library, learning, or
  analysis API implementation. The count read may aggregate existing domain
  tables without adding their final browsing APIs.

## Forbidden Changes

- Do not add `catalog_mode`, presentation-profile, route, or UI metadata to
  governance results, database tables, or `governance_rules_v2.json`.
- Do not create mock counts, trends, freshness values, or review totals.
- Do not route the Asset Center through the generic `/assets` table and present
  it as a completed business view.
- Do not alter the generic asset state machine, normalized-reference contract,
  domain projection ownership, or Open API.
- Do not remove underlying lineage or audit data merely because IA-1 does not
  expose trace interactions.

## Deliverables

- Asset Center route registry, page shell, resource route shells, real count
  loading/failure states, and responsive loading state.
- One authenticated `/internal/v1/asset-center/counts` aggregate read with no
  frontend N+1 calls.
- Seven-group Console navigation and Asset Center breadcrumbs.
- Legacy `/data-assets` redirect with obsolete mock implementation removed.
- Updated `/assets` label and page positioning.
- Focused frontend tests and documentation updates.

## Acceptance

- `/asset-center` presents exactly five business domains; every resource shows
  a real count or an explicit unavailable state, with no synthetic trend/review
  values or `产业画像` entry.
- Domain cards link directly to resource views and contain no link to a
  domain-summary page. Domain-only and unknown paths return not found.
- `标准课程库` is a distinct business entry and counts existing
  `teaching_standard_course` records.
- Every frozen resource href resolves within the Asset Center route shell.
- Policy pages expose the frozen all/national/provincial/regional navigation
  semantics without adding governance classifications.
- `/data-assets` redirects to `/asset-center`.
- `/retrieval-test` redirects to `/query`; there is no second-level
  `智能检索`/`检索联调` distinction.
- `/assets` remains functional and is labeled `全部资产台账`.
- Sidebar and breadcrumbs reflect the seven first-level groups.
- Existing role checks are not expanded or redesigned in this slice.
- No migration, governance-rule, Open API, or asset lifecycle changes are
  present.
- Typecheck, focused Vitest, lint for changed files, production build, and
  desktop/tablet visual inspection pass.

## Review Gates

- **Frontend UX Gate**: five-domain hierarchy and fixed routes match the
  approved business-task IA; the page is operationally restrained, responsive,
  and contains no mock statistics or misleading completed-data claims.
- **Acceptance Gate**: documentation and implementation agree; `/assets`
  continues to serve the technical ledger and no out-of-scope backend or
  governance behavior changes.

## Verification Evidence

- API Contract Gate: focused API test passed and confirms the aggregate count
  endpoint executes exactly two SQL statements regardless of resource count.
  Asset-bounded entries use current catalog references; existing domain
  libraries/records use their owning tables; unimplemented future models
  truthfully return zero.
- `PYTHONPATH=../nexus-app:. .venv/bin/python -m compileall -q nexus_api`:
  passed.
- `npm run typecheck`: passed.
- Focused Vitest for the Asset Center catalog, navigation, and overview:
  3 files and 11 tests passed.
- ESLint for all changed Asset Center Console implementation and test files:
  passed with no findings.
- `npm run build`: passed. Only the existing workspace-root, middleware
  deprecation, and CSS `:global` parser warnings remain.
- Frontend UX Gate: Playwright with a valid local session passed 8 scenarios on
  Chromium desktop and Chromium tablet. Screenshots confirm a compact
  three-column desktop layout, a two-column tablet layout, five restrained
  domain accents, readable `3,936`/`537` counts, and no horizontal overflow or
  overlapping content.
- Route acceptance confirms every subtype links directly to its resource view,
  `/asset-center/policy` renders the not-found state, and retired
  `/data-assets` and `/retrieval-test` routes redirect to their frozen targets.
- Naming acceptance confirms `标准课程库` remains an independent subtype at
  `/asset-center/major/standard-course-library`; no `标准课程` asset type or
  obsolete `teaching-standards/courses` route is exposed.
- `git diff --check`: passed.

The API Contract, Frontend UX, and Acceptance Gates pass for IA-1. Final
domain-specific list fields and interactions remain deferred. Mobile-specific
navigation and layout remain excluded because the product has no mobile-client
adaptation requirement.
