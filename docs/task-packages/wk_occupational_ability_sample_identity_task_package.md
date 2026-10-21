# Task Package: Occupational Ability Sample Identity and Task Views

## Status

Implementation verified; human Data Contract, API Contract, and Frontend UX Review Gates pending.

## Source Context

- `AGENTS.md`: normalize Pipeline B workbooks before domain projection; preserve audit and idempotency.
- `SPEC.md` and Prototype v2.2: Asset Center owns the occupational ability list and its Drawers.
- `WORKFLOWS.md`: data model, API, and P0 UX changes require focused tests and Review Gates.

## Goal

Extract six-digit professional identity from `docs/samples` occupational ability workbook names, show professional code in Asset Center, and scope ability items and graph to a selected typical work task.

## Scope

- Filename identity extraction, PGSD letter/numeric task-sheet detection and projection, profile evidence, normalized record projection, domain row, migration, and internal list/detail API.
- Asset Center occupational ability list, ability item Drawer, graph Drawer, focused tests, and contract documentation.

## Out Of Scope

- New analysis models or changes to governance thresholds.
- Governance admission changes, new graph builds, and changes to the public `/open/v1` API.

## Forbidden Changes

- Do not infer a professional name from an ambiguous filename without confirmed code-to-name evidence or reopen raw workbooks during domain projection.
- Do not change asset lifecycle, permissions, or the graph's persisted facts.

## Acceptance

- A `530706-商务数据分析与应用-...xlsx` PGSD record stores code `530706` and name `商务数据分析与应用`.
- A `730702-典型工作任务表+...xlsx` record stores code `730702` and the user-confirmed name `跨境电子商务`; explicit structured evidence retains precedence.
- The list displays code; task selection changes the item API's `task_code` and the graph's task-rooted subgraph.
- All 13 supplied PGSD workbooks are detected and project non-empty tasks and ability items; cross-sheet P-code conflicts remain review candidates.
- Extraction, writer, API, component tests and relevant static checks pass.

## Review Gates

- Data Contract: identity is evidence-bound, nullable, and persisted from normalized records.
- API Contract: `major_code` is additive on the internal ability-analysis response.
- Frontend UX: selector loads tasks, defaults to the first, and handles empty/error states.

## Verification Evidence

- All 13 supplied `.xlsx` workbooks match the ability-analysis profile, project 6-10 uniquely identified tasks and non-empty ability items, and retain filename professional codes. Eleven auto-admit; `330702` and `730701` remain review candidates because P ability codes recur across task sheets. The code-only `730702` title resolves to the user-confirmed professional name `跨境电子商务`.
- Focused application suite: 91 tests pass, including real workbook projection and writer persistence.
- Frontend: six focused tests pass; TypeScript check and `git diff --check` pass.
- Internal analysis API include suite: eight tests pass against the migrated local PostgreSQL database, including additive `major_code` and `education_level` fields.
- Local database upgraded from `20261020_0119` to `20261021_0120`. The existing `730702` analysis row now stores `730702 / 跨境电子商务 / 中职`, with one migration audit record.
- ESLint cannot start in this checkout because `eslint-plugin-testing-library` is missing from `node_modules`.
- Existing Next.js dev server responds at `http://127.0.0.1:3002/asset-center/major/occupation-analyses` with the expected unauthenticated login redirect.
