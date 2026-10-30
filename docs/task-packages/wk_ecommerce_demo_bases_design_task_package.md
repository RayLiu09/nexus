# Task Package: 电子商务示范基地只读业务视图方案设计

## Status

Design delivered. The source snapshot, PostgreSQL migration, deterministic
initializer, and development-database load are now implemented. Console/API
read views remain a separate implementation slice and the applicable human
Review Gates remain pending.

## Source Context

- `AGENTS.md`, `WORKFLOWS.md`: bounded task packages and applicable Review Gates.
- `ARCHITECT.md`: business Asset Center boundary, independent reference domains,
  PostgreSQL storage, raw retention, and governance input constraints.
- `SPEC.md`, `readme.md`: market domain, authenticated Console reads, real counts.
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: Asset Center
  navigation, resource views, filters, loading/error states.
- `docs/task-packages/wk_business_asset_center_ia1_task_package.md` and
  `wk_market_catalog_api_counts_task_package.md`: route registry and aggregate counts.
- User request: add `电子商务示范基地` under `市场数据`, with national and
  provincial views sourced from the two supplied JSON files. Persist the data
  in the database; all later queries use the database; no editing or deletion.
- Reference: <https://dzswgf.mofcom.gov.cn/ecps/sfjd/index>.

## Goal

Produce a concrete implementation proposal for persisted, read-only national
and provincial ecommerce demonstration-base records, with an accurate national
distribution view and an accurate provincial list.

## Scope

- Inspect existing market routes, list APIs, authentication, and count conventions.
- Inspect both sample files and the reference page HTML and inline scripts.
- Define navigation, fields, storage, initialization, read APIs, statistics,
  source coverage, read-only behavior, failure states, implementation slices,
  tests, and Review Gates.
- Write `docs/ecommerce_demo_bases_implementation_design.md`.

## Out Of Scope

- Implementing or deploying schema, importer, APIs, or UI in this design task.
- Online collection, scheduled synchronization, transaction indicators, exports,
  source-detail scraping, semantic/vector retrieval, and AI governance.
- Any product operation to add, edit, delete, or replace base records.

## Forbidden Changes

- Do not modify existing unrelated work or the earlier untracked ecommerce
  big-data proposal.
- Do not infer provincial identity from names or interpret CSS as geography.
- Do not use source-declared totals as persisted row counts.
- Do not expose raw JSON directly as governance results or invent asset status.
- Do not introduce a new gateway, IAM, MQ, or runtime service.
- Do not mark unimplemented behavior or pending Review Gates as passed.

## Deliverables

- This bounded design task package.
- A Chinese implementation design with proposed storage and read API contracts.
- Sample and source-page verification evidence, and implementation acceptance cases.

## Acceptance And Verification

- National sample: 30 region groups, 170 unique source paths, batch counts
  34 / 63 / 73; no missing required base fields.
- Provincial sample: 142 records fetched from all six source province entries
  (Jiangsu 79, Shandong 33, Henan 9, Hubei 18, Guangxi 1, Gansu 2); each
  province page metadata is retained; the endpoint row itself has no province
  field, so the requested province/code is stored as collection metadata.
- Explicitly distinguish recognition period from source publication time,
  source link flags from base level, and local data count from source totals.
- Specify database-backed queries and the absence of mutation interfaces.
- `git diff --check -- docs/task-packages/wk_ecommerce_demo_bases_design_task_package.md docs/ecommerce_demo_bases_implementation_design.md`.

## Review Gates

The implementation slices must provide Data Model, API Contract, Permission
And Audit, Frontend UX, and Acceptance Gate evidence before merge. No current
asset-version state, AI governance, or semantic retrieval change is proposed.
This design does not claim implementation approval or production validation.
