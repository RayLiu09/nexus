# Task Package: Course Standard Capability Graph

## Task name

Add a second, evidence-bound course-standard graph path while preserving the
existing professional-teaching-standard graph unchanged.

## Source context

- `ARCHITECT.md`: governance and graph inputs are normalized assets only; no
  raw files, raw JSON, or MinerU output may be graph inputs.
- `SPEC.md`: graph results must remain traceable to a normalized reference and
  source evidence.
- `WORKFLOWS.md`: capability-graph vocabulary changes require an architecture,
  semantic-retrieval, and version-state review.

## Goal

Support two evidence-bound standard-document graph projections under the
existing `teaching_standard` governance classification:

1. Professional teaching standards retain their existing graph:
   `Major -> OccupationalDomain -> TypicalWorkTask -> SkillKnowledgeRequirement`.
2. Course standards build a separate graph from a normalized `课程内容与要求`
   table:
   `Course -> CourseModule -> CourseContent`, with `SkillRequirement` and
   `KnowledgeRequirement` as parallel fourth-level children.

## Frozen contracts

- The course-standard extractor accepts only normalized-document table blocks
  with one literal column from each controlled alias group: module
  (`课程模块`/`项目`/`章`/`节`/`工作模块`), content
  (`课程内容`/`教学任务`/`工作任务`/`学习单元`), skill
  (`技能要求`/`技能内容`), knowledge (`知识要求`/`知识内容`), plus an
  `学时` or `课时` header anchor. Columns may be reordered or expressed as a
  two-row header. Free-text inference and raw-source parsing are out of scope.
- Every emitted leaf carries its source block IDs, table row index, and raw
  normalized table row as evidence.
- The graph root is the literal normalized-document `title`, cleaned only by
  removing special symbols and a terminal `课程标准` suffix; no body-text title
  inference is allowed. It connects to each literal course module.
- Course-standard builds use `build_type=course_standard`; they do not reuse
  `build_type=teaching_standard`, `Major`, or `OccupationalDomain` nodes.
- A document may produce at most one generated build for each build type.
- Missing or structurally incomplete course-standard tables are skipped with
  a traceable audit detail; they never produce empty graph envelopes.

## Scope

- `nexus-app/nexus_app/teaching_standard/`
- `nexus-app/nexus_app/capability_graph/`
- `nexus-app/nexus_app/pipeline/stages.py`
- `nexus-app/nexus_app/worker/runner.py`
- `nexus-console/app/assets/[assetId]/_components/`
- `nexus-console/components/AssetDetailTabs.tsx`
- `nexus-console/app/assets/[assetId]/page.tsx`
- focused unit and pipeline tests
- `ARCHITECT.md`, `SPEC.md`, `readme.md`, and this task package

## Out of scope

- Changing the first-class professional teaching-standard extraction or graph.
- LLM extraction fallback for course standards.
- Public graph APIs, graph operations UI, new queues, or direct historical DB
  backfills. A user-authorized, service-backed, audit-recorded rebuild of one
  normalized reference is permitted for recovery; it must not use direct SQL
  inserts or mutate raw/normalized source content.

## Forbidden changes

- Do not graph raw file content, raw MinerU output, or non-evidenced prose.
- Do not infer course modules, tasks, skills, or knowledge requirements that
  are not literal values in a normalized table row.
- Do not add reverse pointers on asset, asset version, or normalized ref.
- Do not bypass governance, audit, or the existing idempotent build service.

## Deliverables

- A strict course-standard table extractor and typed normalized payload.
- `course_standard` capability graph build with the frozen node/edge chain.
- Worker dispatch and audit detail for both standard graph paths.
- Asset-detail knowledge view detects a generated `course_standard` build,
  labels it as `课程知识图谱`, and requests that build type without mixing it
  with the professional-standard `岗位知识图谱`; its `Course` root and four
  downstream node layers use a deterministic left-to-right tree layout, with
  the first three levels expanded by default. Clicking a third-level course
  content node toggles its parallel fourth-level skill and knowledge children;
  the course graph shows no toolbar.
- Unit coverage for extraction, evidence, graph topology, first-path
  non-regression, and absent-table skip behavior.
- Contract documentation updates.

## Acceptance

```bash
cd nexus-app
uv run pytest tests/test_teaching_standard_graph.py tests/test_course_standard_graph.py
```

- A professional teaching-standard payload produces exactly its existing
  `teaching_standard` graph topology.
- A valid course-content table produces only the frozen course-standard graph
  topology with source table evidence on every non-root relation.
- A course standard without all required columns creates no graph build.
