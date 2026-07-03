# Course Textbook Knowledge Processing Implementation Plan

Status: draft for implementation
Date: 2026-07-03
Source design: `docs/course_textbook_knowledge_processing_design.md`

## 1. Objective

Implement the course textbook knowledge-processing optimization described in
`docs/course_textbook_knowledge_processing_design.md` without changing the NEXUS
v3.0 architecture boundary.

The implementation adds a Task Outline path for `course_textbook` assets that
are training-operation oriented, while keeping `knowledge_chunk` as the single
retrieval, QA, indexing, locator, and Evidence Graph candidate foundation.

Target outcome:

```text
normalized_asset_ref(document)
  -> course_textbook subtype detection
  -> processing profile routing
      theory_knowledge     -> semantic_repack chunks -> Evidence Graph eligible
      training_operation   -> task_outline tables -> task-aware chunks
      hybrid               -> semantic chunks now; chapter routing later
      unknown              -> semantic chunks + review signal
  -> unified knowledge_chunk
  -> search / QA / source preview / optional graph build
```

## 2. Binding Constraints

This plan is constrained by the root contracts:

- Governance and knowledge processing input remains `normalized_asset_ref`.
- Do not build from raw files, raw JSON, MinerU raw output, or page fragments.
- Do not replace or fork `knowledge_chunk`.
- Do not add a `task_chunk` or `training_task_chunk` table.
- Do not introduce an enterprise IAM dependency or a custom `llm-gateway`.
- Do not make Evidence Graph mandatory for all textbooks.
- Do not implement enterprise training task extraction in the first delivery
  slice; only reserve model/profile compatibility.
- Keep external business APIs under `nexus-api`; console-only control APIs stay
  internal.
- Every persisted domain result must preserve `normalized_ref_id`,
  `source_block_ids`, and `locator` traceability.

## 3. Existing Baseline

Current implemented or planned baseline found in the repository:

- `course_textbook` governance classification already maps to `textbook_kb`.
- `textbook_kb` currently enters the Knowledge Pipeline through
  `semantic_repack` and emits `knowledge_chunk(chunk_type=semantic_block)`.
- Evidence Graph candidate selection currently loads all semantic chunks for a
  `normalized_ref_id` and filters by anchor role, quality, and content.
- Console document knowledge view currently offers RAG chunks and Evidence Graph
  tabs.

The new work should extend this baseline instead of replacing it.

## 4. Interface Freeze

### 4.1 Profile Enum Values

Use string values to avoid broad enum churn unless the existing enum pattern
requires DB-level enums.

`textbook_subtype`:

- `theory_knowledge`
- `training_operation`
- `hybrid`
- `unknown`

`processing_profile`:

- `evidence_graph`
- `task_outline`
- `hybrid`
- `semantic_only`

`evidence_graph_admission`:

- `recommended`
- `not_recommended`
- `chapter_selective`
- `unknown`

`task_profile`:

- `textbook_training_operation`
- `enterprise_training_task` reserved, not automatically emitted in the first
  delivery slice

`task_outline_node.node_type`:

- `book`
- `project`
- `task`
- `task_section`
- `operation_step`
- `task_artifact`
- `assessment`

`task_outline_node.section_type`:

- `task_objective`
- `task_background`
- `task_analysis`
- `knowledge_prepare`
- `operation_steps`
- `task_artifact`
- `source_resource`
- `task_reflection`
- `assessment`

### 4.2 Database Tables

Add `task_outline_profile`.

Minimum columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | string UUID PK | Same local UUID style as existing models |
| `normalized_ref_id` | FK string | References `normalized_asset_ref.id` |
| `asset_version_id` | string | Version anchor copied from ref |
| `asset_profile` | string | `course_textbook` initially |
| `title` | string nullable | Textbook title or normalized ref title |
| `textbook_subtype` | string nullable | Course textbook subtype |
| `task_profile` | string nullable | `textbook_training_operation` initially |
| `subtype_confidence` | numeric | 0 to 1 confidence |
| `processing_profile` | string | Routing decision |
| `evidence_graph_admission` | string | Graph recommendation |
| `source_block_ids` | JSON list | Evidence blocks for profile decision |
| `quality` | JSON object | Task-outline quality metrics/status |
| `metadata` | JSON object | Evidence, counters, reserved extension fields |
| `created_at` / `updated_at` | timestamp | Use `TimestampMixin` |

Constraints and indexes:

- Unique active/latest profile per `normalized_ref_id` and `asset_profile` for
  P0. If rebuild history is needed later, add `build_no` or status in a later
  slice.
- Index `normalized_ref_id`.
- Index `asset_version_id`.
- No reverse pointer on `normalized_asset_ref` or `asset_version`.

Add `task_outline_node`.

Minimum columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | string UUID PK | Stable node id |
| `normalized_ref_id` | FK string | References `normalized_asset_ref.id` |
| `profile_id` | FK string | References `task_outline_profile.id` |
| `parent_id` | FK string nullable | Self-reference |
| `node_type` | string | See frozen values |
| `section_type` | string nullable | See frozen values |
| `title` | text nullable | Node title |
| `content` | text nullable | Node body/instruction |
| `summary` | text nullable | Short summary |
| `order_no` | integer | Sibling order |
| `depth` | integer | Tree depth |
| `source_block_ids` | JSON list | Required unless generated from parent only |
| `locator` | JSON object nullable | Same locator contract as chunks where possible |
| `metadata` | JSON object | Tools, inputs, outputs, fields, task titles |
| `created_at` / `updated_at` | timestamp | Use `TimestampMixin` |

Constraints and indexes:

- Index `normalized_ref_id`.
- Index `profile_id`.
- Index `parent_id`.
- Index `(profile_id, order_no)`.
- No chunk id foreign key on the node table; projection relation lives in
  `knowledge_chunk.chunk_metadata.outline_node_id`.

### 4.3 `knowledge_chunk.chunk_metadata`

Do not add columns for Task Outline projection in the first delivery. Encode the
projection in `chunk_metadata`:

```json
{
  "semantic_variant": "task_outline_repack",
  "domain_model": "task_outline.v1",
  "task_profile": "textbook_training_operation",
  "textbook_subtype": "training_operation",
  "outline_node_id": "node-step-003",
  "project_title": "项目一 基础数据采集",
  "task_title": "任务一 市场数据采集",
  "node_type": "operation_step",
  "section_type": "operation_steps",
  "step_no": 3,
  "anchor_role": "operation_step",
  "section_processing_profile": "task_outline",
  "graph_candidate": false
}
```

Keep:

- `knowledge_type_code = textbook_kb`
- `chunk_type = semantic_block`
- `chunking_strategy = semantic_repack` for compatibility, unless a later
  migration explicitly adds `task_outline_repack`.

### 4.4 Internal API Surface

Use internal control-plane APIs first. Public/open APIs are out of scope for the
initial implementation.

Recommended internal endpoints:

```text
GET  /internal/v1/normalized-refs/{ref_id}/task-outline
POST /internal/v1/normalized-refs/{ref_id}/task-outline/rebuild
GET  /internal/v1/task-outline/profiles/{profile_id}
GET  /internal/v1/task-outline/nodes/{node_id}
```

Response shape for `GET /internal/v1/normalized-refs/{ref_id}/task-outline`:

```json
{
  "profile": {
    "id": "...",
    "normalized_ref_id": "...",
    "asset_profile": "course_textbook",
    "textbook_subtype": "training_operation",
    "processing_profile": "task_outline",
    "evidence_graph_admission": "not_recommended",
    "subtype_confidence": 0.91,
    "quality": {}
  },
  "nodes": [
    {
      "id": "...",
      "parent_id": null,
      "node_type": "project",
      "section_type": null,
      "title": "项目一 基础数据采集",
      "summary": "...",
      "order_no": 1,
      "depth": 1,
      "source_block_ids": ["block-p10-001"],
      "locator": {},
      "metadata": {}
    }
  ],
  "chunk_projection": {
    "projected_chunk_count": 24,
    "stale_chunk_count": 0
  }
}
```

## 5. Implementation Phases

### Phase 0: Contract Package

Goal: freeze the task package before data model and pipeline work.

Tasks:

1. Create `docs/task-packages/wk_course_textbook_task_outline_task_package.md`.
2. Record the frozen profile values, APIs, owned files, and Review Gates.
3. Update `ARCHITECT.md`, `SPEC.md`, and `readme.md` only if the human owner
   decides Task Outline is now part of the active P0/P1 contract rather than a
   design extension.

Deliverables:

- Task package document.
- No code changes.

Review Gates:

- Data Model Gate, because new domain tables are planned.
- RAGFlow Integration Gate, because chunk projection affects indexing input.
- Frontend UX Gate, if Console work enters the same cycle.

Acceptance:

- Task package names allowed modules and forbidden changes.
- Review gates and test commands are explicit.

### Phase 1: Data Model And Schemas

Goal: add Task Outline persistence without changing the existing asset/version
contract.

Owned files:

- `nexus-app/nexus_app/models.py`
- `nexus-app/nexus_app/enums.py`, only if enum classes are locally preferred
- `nexus-app/alembic/versions/*`
- `nexus-app/tests/` model and migration tests

Tasks:

1. Add `TaskOutlineProfile` and `TaskOutlineNode` ORM models.
2. Add Alembic migration for both tables and indexes.
3. Add Pydantic/domain schemas for profile and node DTOs in the existing app
   schema location.
4. Add repository/service helpers for:
   - upsert profile by `normalized_ref_id` and `asset_profile`
   - replace nodes for a profile idempotently
   - list tree nodes in `(depth, order_no)` or preorder order
5. Add tests for constraints, JSON defaults, FK integrity, and no reverse
   pointers on normalized refs or versions.

Acceptance:

- Migration upgrades and downgrades cleanly.
- A profile and a small project/task/step tree can be persisted and queried.
- No columns are added to `normalized_asset_ref`, `asset_version`, or
  `knowledge_chunk` for reverse links.

### Phase 2: Subtype Detection And Processing Routing

Goal: classify `course_textbook` normalized documents into textbook subtypes and
store a Task Outline profile decision.

Owned files:

- New module: `nexus-app/nexus_app/task_outline/`
- Knowledge orchestration boundary in `nexus-app/nexus_app/knowledge/services.py`
  or a narrow caller around it
- Focused tests under `nexus-app/tests/task_outline/`

Tasks:

1. Implement deterministic first-pass subtype detection over
   `normalized_document.blocks[]` and `body_markdown`.
2. Use weighted signals:
   - task keywords: `项目`, `任务`, `任务目标`, `任务背景`, `任务分析`,
     `任务实施`, `操作步骤`, `任务思考`, `实践训练`
   - theory keywords: `概念`, `定义`, `原理`, `机制`, `分类`, `影响因素`,
     `知识点`, `理论基础`
   - table/image roles from block metadata when available
   - heading and short-title structure
3. Persist `TaskOutlineProfile` for `course_textbook` refs:
   - `training_operation` -> `processing_profile=task_outline`,
     `evidence_graph_admission=not_recommended`
   - `theory_knowledge` -> `processing_profile=evidence_graph`,
     `evidence_graph_admission=recommended`
   - `hybrid` -> `processing_profile=hybrid`,
     `evidence_graph_admission=chapter_selective`
   - `unknown` -> `processing_profile=semantic_only`,
     `evidence_graph_admission=unknown`
4. Store `subtype_evidence` and matched source blocks in profile metadata.
5. Make the detector idempotent for rebuilds.

Acceptance:

- The sample `c62de38a-2070-40fb-beb6-26798898982d` is expected to classify as
  `training_operation` when its normalized blocks are present.
- Theory-like fixtures classify as `theory_knowledge`.
- Ambiguous fixtures classify as `unknown` or `hybrid`, not forcibly as task.
- Existing `textbook_kb` semantic chunking still works when no Task Outline path
  is selected.

### Phase 3: Task Outline Extraction

Goal: extract a minimal project/task/section/step/artifact tree for
`training_operation` textbooks.

Owned files:

- `nexus-app/nexus_app/task_outline/extractor.py`
- `nexus-app/nexus_app/task_outline/normalizer.py`
- `nexus-app/nexus_app/task_outline/quality.py`
- `nexus-app/tests/task_outline/`

Tasks:

1. Normalize heading and key-label patterns:
   - textbook headings such as `任务目标`, `任务背景`, `任务分析`, `任务实施`,
     `任务思考`
   - short titles that MinerU emitted as paragraph blocks
2. Detect project/module boundaries.
3. Detect task boundaries.
4. Split task sections by normalized labels.
5. Extract ordered `operation_step` nodes from numbered paragraphs/lists and
   step-like blocks.
6. Bind tables, figures, source resources, and output artifacts to the nearest
   task or step using block order, heading path, captions, and local keywords.
7. Compute node locator from source blocks using the same aggregation semantics
   as chunk locator.
8. Compute quality metrics:
   - `task_coverage`
   - `section_coverage`
   - `step_order_validity`
   - `artifact_binding_rate`
   - `resource_binding_rate`
   - `locator_coverage`
   - `chunk_projection_coverage`
   - `noise_ratio`
   - `orphan_block_ratio`
9. Persist the profile and nodes in one transaction.

Acceptance:

- A textbook fixture generates:
  - project nodes
  - task nodes
  - task background/analysis/objective nodes
  - operation step nodes
  - task artifact nodes
- Every high-value node has `source_block_ids`.
- At least 95% of persisted nodes in the fixture have a locator when source
  blocks carry page/bbox data.
- Quality values are persisted in `TaskOutlineProfile.quality`.
- Low-quality outline extraction marks the outline profile as review-worthy in
  profile quality metadata but does not directly change normalized asset
  governance state.

### Phase 4: Task-Aware Chunk Projection

Goal: project high-value Task Outline nodes into unified `knowledge_chunk`.

Owned files:

- `nexus-app/nexus_app/task_outline/projector.py`
- `nexus-app/nexus_app/knowledge/router.py` or a narrow orchestration hook
- `nexus-app/tests/knowledge/` and `nexus-app/tests/task_outline/`

Tasks:

1. Define node projection rules:
   - must project: `task`, `task_objective`, `task_background`,
     `task_analysis`, `knowledge_prepare`, `operation_step`, `task_artifact`
   - may project: `project`, `task_reflection`, `assessment`
   - never project: TOC, copyright pages, appendix-only noise, decorative images
2. Build chunk content templates for:
   - task overview
   - task background/objective/analysis
   - operation step
   - task artifact/resource
3. Emit `KnowledgeChunk` rows with:
   - `knowledge_type_code=textbook_kb`
   - `chunk_type=semantic_block`
   - `chunking_strategy=semantic_repack`
   - `source_block_ids` copied from the node
   - `locator` copied/aggregated from the node
   - `chunk_metadata.domain_model=task_outline.v1`
   - `chunk_metadata.outline_node_id=<node id>`
   - `chunk_metadata.section_processing_profile=task_outline`
   - `chunk_metadata.graph_candidate=false`
4. Ensure projection is idempotent on rebuild:
   - delete/replace prior chunks for the same `normalized_ref_id`,
     `knowledge_type_code`, and `domain_model=task_outline.v1`, or
   - use a deterministic projection key in metadata and update rows.
5. Preserve existing semantic chunks for theory textbooks.
6. Decide for `training_operation` whether to replace generic semantic chunks
   with task-aware chunks or keep both. Recommended P0 behavior: produce only
   task-aware chunks for `training_operation` to avoid duplicate retrieval
   noise, while retaining the same `textbook_kb` knowledge type.

Acceptance:

- Task background, task analysis, operation steps, and task artifacts produce
  chunks.
- Projected chunks link back to outline nodes through
  `chunk_metadata.outline_node_id`.
- Projected chunks can be queried by `normalized_ref_id` and `textbook_kb`.
- Chunk projection coverage is at least 90% for high-value nodes in fixtures.
- Existing search/QA citation shape remains valid because chunks still carry
  `normalized_ref_id`, `source_block_ids`, and `locator`.

### Phase 5: Evidence Graph Admission Control

Goal: prevent task-operation chunks from entering default Evidence Graph
candidate selection while keeping theory textbooks graph-ready.

Owned files:

- `nexus-app/nexus_app/evidence_graph/candidates.py`
- `nexus-app/nexus_app/evidence_graph/profiles.py`, if profile config needs a
  skip rule
- `nexus-app/tests/evidence_graph/`
- `nexus-console/app/assets/[assetId]/_components/EvidenceGraphView.tsx`

Tasks:

1. Update candidate skip logic to treat these metadata combinations as skipped:
   - `graph_candidate=false`
   - `section_processing_profile=task_outline`
   - `domain_model=task_outline.v1` unless a future explicit override is passed
2. Add skip reason such as `task_outline_not_graph_candidate`.
3. Surface dry-run counts and skip reasons through existing internal graph APIs.
4. In Console, when `TaskOutlineProfile.evidence_graph_admission` is
   `not_recommended`, show a warning and weak/confirm the graph build action.
5. Keep `course_textbook/theory_knowledge` mapping to the existing `textbook`
   graph profile.

Acceptance:

- Task-aware chunks are skipped by Evidence Graph candidate selection.
- Theory textbook semantic chunks are still selected.
- Hybrid fixtures can carry both graph-eligible semantic chunks and
  task-outline chunks in a later slice.
- Console makes the graph recommendation visible before build submission.

### Phase 6: Internal API And Console Read View

Goal: make Task Outline visible and source-traceable in asset detail.

Owned files:

- `nexus-api/nexus_api/api/internal/`, if internal APIs are owned there
- `nexus-console/app/api/`, if proxy routes are needed
- `nexus-console/app/assets/[assetId]/_components/DocumentKnowledgeView.tsx`
- New component: `TaskOutlineView.tsx`

Tasks:

1. Add internal API endpoint to fetch profile, nodes, and projection summary.
2. Add internal API endpoint to rebuild outline for a normalized ref. The handler
   should submit a job/build envelope or call the existing background path; it
   must not run heavyweight extraction inline if the extraction becomes LLM or
   long-running.
3. Add a Task Outline tab to document knowledge view.
4. Render a compact tree:
   - project/module
   - task
   - sections
   - steps/artifacts
5. Reuse source preview/locator components for node source jumps.
6. Do not implement rich manual editing in this phase.

Acceptance:

- Users can browse Task Outline for a processed training-operation textbook.
- Users can jump from a task node to source preview using locator/source blocks.
- Empty state clearly distinguishes "not a task-outline asset" from "not built".
- Evidence Graph tab shows not-recommended state for training-operation assets.

### Phase 7: Rebuild, Staleness, And Manual Maintenance Foundation

Goal: prepare for later human maintenance without introducing a full operations
workbench.

Tasks:

1. Add rebuild status and projection summary to profile metadata or a minimal
   status field if needed.
2. Mark projected chunks stale when outline nodes are changed in future manual
   edit APIs.
3. Rebuild affected chunks from nodes, not by editing chunks directly.
4. Update `index_manifest` stale status when projected chunks are replaced.
5. Add audit events for rebuild request and projection replacement if existing
   audit event taxonomy supports it.

Acceptance:

- Rebuild is idempotent.
- Rebuild does not create duplicate effective chunks.
- Index staleness is visible after projection replacement.

### Phase 8: Hybrid And Enterprise Training Task Later Slices

This phase is explicitly later scope.

Hybrid textbook tasks:

- Add chapter-level subtype routing.
- Mark theory section chunks as `section_processing_profile=evidence_graph`.
- Mark task section chunks as `section_processing_profile=task_outline`.
- Evidence Graph consumes only graph-ready chunks.

Enterprise training task tasks:

- Enable `asset_profile=enterprise_training_task`.
- Implement key-label normalization for `任务名称`, `背景名称`, `背景内容`,
  `要求`, `资源`, `任务步骤`.
- Support single-task assets without project/module nodes.
- Project to the same `knowledge_chunk` table with
  `task_profile=enterprise_training_task`.

## 6. Recommended Task Packages

### Package A: Contract And Data Model

Task name:

Task Outline profile and node persistence for training-operation textbooks.

Scope:

- Models, migration, schemas, repository helpers, tests, docs task package.

Out of scope:

- Extraction algorithm, chunk projection, Console.

Review Gates:

- Data Model Gate.

Acceptance:

- Migrations pass.
- Profile/node persistence tests pass.

### Package B: Subtype Detection And Outline Extraction

Task name:

Course textbook subtype detector and minimal Task Outline extractor.

Scope:

- Detector, heading/key-label normalization, tree extraction, locator binding,
  quality metrics, tests.

Out of scope:

- Chunk projection and Console.

Review Gates:

- RAGFlow Integration Gate only if pipeline routing is changed.

Acceptance:

- Training-operation fixture builds project/task/step/artifact tree.
- Theory and unknown fixtures route correctly.

### Package C: Task-Aware Chunk Projection

Task name:

Project Task Outline nodes to unified `knowledge_chunk`.

Scope:

- Projection service, knowledge pipeline hook, idempotency, metadata contract,
  tests.

Out of scope:

- New chunk table, public API changes.

Review Gates:

- RAGFlow Integration Gate.
- Permission and Audit Gate if projection affects search/QA returned fields.

Acceptance:

- High-value nodes project to chunks with `outline_node_id`.
- Search/QA citation contracts remain intact.

### Package D: Evidence Graph Admission

Task name:

Skip Task Outline chunks from default Evidence Graph candidate selection.

Scope:

- Candidate selector skip logic, dry-run reason, tests, Console warning if small
  enough.

Out of scope:

- Hybrid chapter-level graph selection.

Review Gates:

- RAGFlow Integration Gate.
- Frontend UX Gate for Console messaging.

Acceptance:

- `graph_candidate=false` chunks are skipped with explicit reason.
- Theory textbook chunks still select normally.

### Package E: Console Task Outline Read View

Task name:

Task Outline asset-detail read view.

Scope:

- Internal API, proxy, tree view, source locator action, empty states.

Out of scope:

- Manual node editing.
- Public/open API.

Review Gates:

- API Contract Gate for internal API.
- Frontend UX Gate.

Acceptance:

- Asset detail can browse project/task/step tree.
- Source jump works from nodes.

### Package F: Maintenance And Rebuild Foundation

Task name:

Task Outline rebuild and projection staleness.

Scope:

- Rebuild trigger, idempotent replacement, chunk stale/index stale marking,
  audit where applicable.

Out of scope:

- Full manual maintenance workbench.

Review Gates:

- Version State Gate if version/index state changes.
- Permission and Audit Gate.

Acceptance:

- Rebuild does not duplicate chunks.
- Replaced projection marks index stale.

## 7. Test Matrix

Backend unit tests:

- Subtype detection:
  - `training_operation`
  - `theory_knowledge`
  - `hybrid`
  - `unknown`
- Task Outline extraction:
  - project/task boundary
  - task section boundary
  - numbered step order
  - table/artifact binding
  - locator aggregation
  - quality metric calculation
- Persistence:
  - profile unique constraint
  - node tree ordering
  - JSON default isolation
  - idempotent replace
- Chunk projection:
  - required node types generate chunks
  - noise nodes do not generate chunks
  - metadata contract includes `outline_node_id`
  - `source_block_ids` and `locator` preserved
  - rebuild does not duplicate chunks
- Evidence Graph:
  - task-outline chunks skipped
  - theory chunks selected
  - skip reasons surfaced

API tests:

- `GET /internal/v1/normalized-refs/{ref_id}/task-outline`
- rebuild endpoint authorization and idempotency
- empty/not-built/not-applicable states

Frontend verification:

- Task Outline tab appears only for document refs.
- Empty states distinguish not applicable from not built.
- Tree renders dense textbook structures without text overlap.
- Source locator action opens the existing preview flow.
- Evidence Graph not-recommended message appears for task-operation textbooks.

Suggested focused commands after implementation:

```bash
cd nexus-app
uv run pytest tests/task_outline
uv run pytest tests/knowledge/test_course_textbook_chunks.py
uv run pytest tests/evidence_graph
```

```bash
cd nexus-api
uv run pytest tests
```

```bash
cd nexus-console
npm run lint
npm run test
```

Adjust command names to the actual package scripts before execution.

## 8. Acceptance Criteria

The implementation is complete for the initial delivery when:

1. A normalized `course_textbook` training-operation fixture is classified as
   `training_operation`.
2. The fixture persists a `TaskOutlineProfile` with
   `processing_profile=task_outline` and
   `evidence_graph_admission=not_recommended`.
3. The fixture persists project, task, task-section, operation-step, and
   task-artifact nodes.
4. High-value nodes have `source_block_ids` and locator data.
5. High-value nodes project to `knowledge_chunk` rows under `textbook_kb`.
6. Projected chunks carry `chunk_metadata.outline_node_id`,
   `domain_model=task_outline.v1`,
   `section_processing_profile=task_outline`, and `graph_candidate=false`.
7. Search/QA can still cite `normalized_ref_id`, `chunk_id`, `source_block_ids`,
   and locator without a response-shape regression.
8. Evidence Graph candidate selection skips task-outline chunks by default and
   preserves theory-textbook candidate behavior.
9. Console can read the outline tree and jump to source locations.
10. Enterprise training task profile names and metadata are reserved but no
    automatic enterprise training task extraction is enabled.

## 9. Risks And Controls

| Risk | Control |
| --- | --- |
| Duplicate retrieval noise from generic semantic chunks plus task chunks | For `training_operation`, prefer task-aware chunks as the active `textbook_kb` projection; keep generic semantic path for theory/unknown |
| Task detector misclassifies theory textbooks | Use conservative thresholds; route ambiguous assets to `unknown` or `hybrid` |
| Graph build consumes task steps as conceptual facts | Enforce `graph_candidate=false` and selector skip reason |
| Task tree and chunks drift after future edits | Treat task tree as source of truth; rebuild projected chunks from nodes |
| Locator gaps reduce source traceability | Fail quality metric or mark outline review-worthy when locator coverage is below threshold |
| Enterprise task support leaks into current scope | Keep `enterprise_training_task` only as allowed string/metadata reservation until a later task package |
| Data model violates reverse-pointer rule | No pointers from `normalized_asset_ref`, `asset_version`, or `knowledge_chunk` back to profile/node |

## 10. Documentation Updates

Update these after code lands:

- `ARCHITECT.md`: add `task_outline_profile` and `task_outline_node` only if
  accepted as active architecture, not merely design extension.
- `SPEC.md`: add Console/API/acceptance behavior only when the feature enters
  the active delivery scope.
- `readme.md`: add a short implementation baseline entry when the first
  complete slice is merged.
- `docs/task-packages/`: create or update the bounded weekly task package before
  implementation starts.

