# Task Package: Textbook Knowledge Outline v1

Targets `task_outline_profile.textbook_subtype = "theory_knowledge"` (理论知识型教材). UI feature name: "知识点大纲".

## Source Context

- `CLAUDE.md` / `SPEC.md` / `WORKFLOWS.md`: architecture, product, and task-package contracts.
- `config/governance_rules_v2.json`: read-only reference; classification `course_textbook` → `primary_knowledge_type: textbook_kb`. **Not modified by this slice.**
- `nexus-app/nexus_app/task_outline/detector.py:detect_course_textbook_subtype()`: existing scorer already writes `textbook_subtype` to `task_outline_profile`; already supports `theory_knowledge` (see `_score_theory`, `_looks_like_theory_with_practice_drills`, routing `("evidence_graph", "recommended")`). **Read-only source; not modified.**
- `nexus-app/nexus_app/task_outline/schemas.py:TEXTBOOK_SUBTYPES`: existing set `{theory_knowledge, training_operation, hybrid, unknown}`. **Not modified.**
- `nexus-app/nexus_app/models.py`: `TaskOutlineProfile` (read-only source for gating; `.textbook_subtype` field), `KnowledgeChunk` (extended with new column), `NormalizedAssetRef` (referenced by FK).
- `nexus-app/nexus_app/enums.py`: `JobType` (snake_case values), `AuditEventType` (PascalCase values) — both extended.
- `nexus-app/alembic/versions/20260703_0062_task_outline_tables.py`: closest DDL template — mirror index naming, JSON server defaults, downgrade order.
- `nexus-app/nexus_app/pipeline/stages.py:_persist_normalized_ref`: normalize finalization; outline sub-step slots in after this + after `task_outline_profile` is written.
- `nexus-console/app/assets/[assetId]/_components/DocumentKnowledgeView.tsx`: Segmented host; insertion point immediately after RAG知识块.
- `nexus-console/app/assets/[assetId]/_components/DocumentKnowledgeGraphView.tsx`: **predecessor to be DELETED** — client-side blocks heading extraction produced unsatisfactory graphs (documented in project memory `project_knowledge_outline_replaces_graph_view.md`).
- `nexus-console/app/assets/[assetId]/_components/TaskOutlineView.tsx`: closest analogue for ECharts radial + Segmented tree/radial toggle.
- `nexus-console/lib/usePolling.ts`: pattern for polling job status.
- `nexus-console/app/api/normalized-refs/[refId]/task-outline/route.ts`: Next.js proxy pattern to mirror.

Decisions (2026-07-08):

1. New `knowledge_outline_node` table.
2. Default visualization: radial tree via ECharts (`series-tree layout: 'radial'`).
3. **Synchronous construction** (option 丙-变体, aligned with `task_outline` current pattern): GET auto-builds on first hit when subtype gate matches; POST rebuild replaces existing tree inline. **No JobType.BUILD_KNOWLEDGE_OUTLINE, no async worker, no stale flag, no 202 response.** No `normalize` pipeline integration — outline builds lazily at first API access, chunks are already available by then.
4. UI label: "知识点大纲 / knowledge outline".
5. **Gating**: `task_outline_profile.textbook_subtype == "theory_knowledge"` (reuse existing enum value; no schema change to task_outline).
6. `numbering_path` as JSONB int array (no `ltree` extension).
7. `anchor_range` on leaf nodes only.
8. **Dedicated column** `knowledge_chunk.knowledge_outline_node_id` to avoid namespace conflict with task_outline's `chunk_metadata.outline_node_id`.

## Goal

Replace client-side heading extractor `DocumentKnowledgeGraphView` with a backend-persisted, radial-tree-rendered three-level "知识点大纲" for `theory_knowledge` textbooks. Outline is built deterministically from the MinerU heading tree during `normalize`, persists in `knowledge_outline_node`, and is exposed via read-only APIs plus a manual rebuild job.

## Scope

### Backend

- Alembic migration (single file):
  - Create `knowledge_outline_node` table.
  - Add `knowledge_chunk.knowledge_outline_node_id` (`String(36)` FK, `ON DELETE SET NULL`) + index.
  - Extend PG enum `auditeventtype` with `KnowledgeOutlineBuilt`, `KnowledgeOutlineRebuildRequested`.
- Extend Python enum `AuditEventType` in `nexus_app.enums`. **No `JobType` change.**
- SQLAlchemy model `KnowledgeOutlineNode` in `models.py`; add column + relationship on `KnowledgeChunk`.
- Deterministic outline builder (`nexus_app.knowledge_outline.builder`):
  - Numbering parser: 第X章 / X.Y.Z / Chapter N / 项目 X / 模块 X.
  - Depth-3 truncation (deeper headings become L3 siblings under the same L2).
  - Fallback: no heading → single-node root with `fallback_used=true`.
- Persist service (`nexus_app.knowledge_outline.service`):
  - Heading extractor over normalized payload blocks.
  - Atomic replace-tree.
  - Leaf-node-only backfill of `knowledge_chunk.knowledge_outline_node_id` via `source_block_ids` intersection.
  - Sync entry points invoked from the API layer only. **No `normalize` pipeline integration.**
- Audit emissions via existing `write_audit` with `rules_etag` (from `GovernanceRulesRegistry.get_etag()`) in summary:
  - `KnowledgeOutlineBuilt` on every successful build (GET auto-build or POST rebuild).
  - `KnowledgeOutlineRebuildRequested` when the POST rebuild endpoint fires (operational audit trail).

### API (nexus-api)

Mirror `task_outline` router style (`nexus_api/api/internal/task_outline.py`) under `/internal/v1/` — internal-facing, consumed by Next.js console proxy.

- `GET /internal/v1/normalized-refs/{ref_id}/knowledge-outline` — 200 with tree.
  - Gating: 404 when subtype != `theory_knowledge`.
  - **Auto-build**: if subtype matches and no outline exists yet, build inline (single transaction), then return.
- `POST /internal/v1/normalized-refs/{ref_id}/knowledge-outline/rebuild` — 200 with fresh tree (synchronous, replaces existing).
  - Emits `KnowledgeOutlineRebuildRequested` before rebuild and `KnowledgeOutlineBuilt` on completion.
- `GET /internal/v1/knowledge-outline-nodes/{node_id}/chunks?limit=&cursor=` — cursor-paginated chunks under subtree.
- `GET /internal/v1/knowledge-outline-nodes/{node_id}/preview` — first-N-sentences summary (no LLM).
- Permission inherited via existing `normalized_asset_ref` guard; no new policy.

### Next.js Console Proxy (mirror `task-outline` pattern)

- `nexus-console/app/api/normalized-refs/[refId]/knowledge-outline/route.ts` — GET.
- `nexus-console/app/api/normalized-refs/[refId]/knowledge-outline/rebuild/route.ts` — POST (sync).
- `nexus-console/app/api/knowledge-outline-nodes/[nodeId]/chunks/route.ts` — GET.
- `nexus-console/app/api/knowledge-outline-nodes/[nodeId]/preview/route.ts` — GET.

### Frontend

- New `KnowledgeOutlineView.tsx` (client component; ECharts `series-tree layout: 'radial'`; Segmented `tree | radial` sub-toggle mirroring `TaskOutlineView`).
- Node click → Antd `Drawer` with chunks list; deep-link to raw preview via `anchor_range`.
- Manual rebuild → Antd `Modal.confirm` two-step confirmation → POST rebuild → replace in-place with returned fresh tree (no polling; endpoint is sync).
- Loading / Error / Empty via existing `ApiState` + Antd `Skeleton` / `Empty`.
- Integrate into `DocumentKnowledgeView.tsx`:
  - Insert Segmented option "知识点大纲" immediately after `RAG知识块`.
  - Gate: `showKnowledgeOutline = taskProfile?.textbook_subtype === "theory_knowledge"`.
  - Remove `KNOWLEDGE_GRAPH_VIEW_OPTION` and its render branch.
- Delete `DocumentKnowledgeGraphView.tsx` and any dead helpers unique to it.

## Out Of Scope

- LLM-based knowledge-point extraction; cross-node relations.
- Cross-document outline aggregation.
- Adding new `textbook_subtype` enum values or modifying detector logic.
- Modifying `TaskOutlineProfile` schema; treat as read-only.
- Modifying `EvidenceGraphView` or its gating; it continues to show for `theory_knowledge` assets alongside knowledge outline.
- `ltree` PostgreSQL extension migration.
- Outline versioning / diff between rebuilds.
- Modifying `governance_result` / `ai_governance_run` / `ai_prompt_profile` / quality scoring.
- Modifying `governance_rules_v2.json`.
- Outline surfacing in search / QA API results.
- **Asynchronous rebuild via job worker; new `JobType` values; stale-flag semantics; poll-based rebuild UX**. Construction is synchronous throughout.
- **`normalize` pipeline coupling**. Outline is built lazily on first API access, not during pipeline stages.

## Forbidden Changes

- Do not call any LLM in outline construction; step must be deterministic.
- Do not modify `detector.detect_course_textbook_subtype()`, `TEXTBOOK_SUBTYPES`, or `task_outline_profile` schema; treat as read-only inputs.
- Do not inline any anchor markers in normalized markdown; `anchor_range` stays strictly out-of-band (see `feedback_md_char_range_out_of_band` memory).
- Do not add a new pipeline stage or hook outline construction into `normalize`; construction is API-triggered only (GET auto-builds, POST rebuilds).
- Do not add a new `JobType` value or worker for outline construction.
- Do not reuse the key `chunk_metadata.outline_node_id` — that belongs to task_outline chunk projection. Use the dedicated column `knowledge_outline_node_id`.
- Do not add reverse pointers between `knowledge_outline_node` and `governance_result` / `ai_governance_run` / `ai_prompt_profile`.
- Do not change existing `knowledge_chunk` contract fields; only ADD `knowledge_outline_node_id`.
- Do not introduce AntV G6 or any second graph library; ECharts only.
- Do not modify `governance_rules_v2.json` in this slice.
- Do not silently downgrade gating (must strictly filter by `theory_knowledge`).
- Do not persist chunk plaintext, raw source text, or model output in audit logs.

## Deliverables

### Backend

- `nexus-app/alembic/versions/20260708_0065_knowledge_outline_node.py`:
  - CREATE TABLE `knowledge_outline_node`: `id` (String 36 PK), `normalized_ref_id` (FK CASCADE), `parent_id` (self-FK CASCADE), `level` int, `order_index` int, `title` text, `numbering` (String 64), `numbering_path` JSON, `anchor_range` JSON, `chunk_count` int, `build_run_id` (String 36), `fallback_used` bool, `metadata` JSON, timestamps.
  - Constraints: `UNIQUE(normalized_ref_id, parent_id, order_index)`, `CHECK(level BETWEEN 0 AND 3)`, indexes on `(normalized_ref_id, level)`, `parent_id`, `build_run_id`.
  - ALTER TABLE `knowledge_chunk` ADD COLUMN `knowledge_outline_node_id` + index.
  - `ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS` for `KnowledgeOutlineBuilt` and `KnowledgeOutlineRebuildRequested`. **No `jobtype` extension.**
- `nexus-app/nexus_app/models.py`: `KnowledgeOutlineNode` class; add column + relationship on `KnowledgeChunk`.
- `nexus-app/nexus_app/enums.py`: extend `AuditEventType` with two values. **No `JobType` change.**
- `nexus-app/nexus_app/knowledge_outline/__init__.py`.
- `nexus-app/nexus_app/knowledge_outline/builder.py`: `build_outline(...) -> OutlineBuildResult`.
- `nexus-app/nexus_app/knowledge_outline/service.py`:
  - `extract_headings_from_blocks(blocks) -> list[HeadingInput]`.
  - `build_and_persist_outline(session, ref, payload, *, actor_type, actor_id, trace_id) -> OutlineBuildOutcome` (atomic replace-tree + leaf chunk backfill + audit).
  - `get_outline_tree(session, ref_id) -> OutlineTree | None`.

### API

- `nexus-api/nexus_api/api/internal/knowledge_outline.py`: 4 endpoints (mirror `task_outline.py` structure).
  - Sync GET auto-build; sync POST rebuild; both return the full tree envelope.
- Router registration in `nexus-api/nexus_api/api/internal/__init__.py`.

### Frontend

- `nexus-console/lib/api.ts`: types + fetch helpers (`getKnowledgeOutline`, `getKnowledgeOutlineChunks`, `getKnowledgeOutlinePreview`, `rebuildKnowledgeOutline`).
- 4 Next.js proxy `route.ts` files listed under Scope.
- `nexus-console/app/assets/[assetId]/_components/KnowledgeOutlineView.tsx`.
- Update `nexus-console/app/assets/[assetId]/_components/DocumentKnowledgeView.tsx`.
- **Delete** `nexus-console/app/assets/[assetId]/_components/DocumentKnowledgeGraphView.tsx`.

### Tests

- `nexus-app/tests/knowledge_outline/test_builder.py`: well-formed tree, missing L1, non-monotonic levels, deep collapse, numbering parsing, fallback root.
- `nexus-app/tests/knowledge_outline/test_service.py`: heading extraction from blocks, atomic replace (prior tree fully overwritten on rebuild), leaf-only chunk backfill via block-id intersection, audit events emitted with `rules_etag`.
- `nexus-api/tests/test_knowledge_outline_api.py`: GET returns 404 for non-`theory_knowledge` refs; GET auto-builds on first hit and returns 200; POST rebuild replaces prior tree; chunks/preview endpoints; permission inheritance.
- `nexus-console/app/assets/[assetId]/_components/__tests__/KnowledgeOutlineView.spec.tsx`: Segmented gating, node click drawer, rebuild confirm flow, Empty / Error rendering.

## Acceptance

- A `theory_knowledge` normalized_ref's first outline GET returns 200 with a freshly built tree; depth ≤ 3. Subsequent GETs return the persisted tree without rebuilding.
- A theory book without any recognizable heading yields a single-node root with `fallback_used=true`; API returns 200 (not 404).
- A non-`theory_knowledge` normalized_ref (or one with null `textbook_subtype`) has no `knowledge_outline_node` rows; GET returns 404.
- POST rebuild returns 200 with the fresh tree; prior tree rows are fully replaced (no orphaned rows on the same `normalized_ref_id`).
- `knowledge_chunk.knowledge_outline_node_id` is populated only on leaf nodes; internal nodes have zero chunk associations.
- Audit events `KnowledgeOutlineBuilt` (on every successful build) and `KnowledgeOutlineRebuildRequested` (on every POST rebuild) include `rules_etag`; audit logs contain no chunk plaintext or model output.
- Frontend on `theory_knowledge` asset: Segmented shows `RAG知识块 → 知识点大纲 → …`; radial tree renders; node click opens Drawer.
- Frontend on non-`theory_knowledge` asset: 知识点大纲 absent.
- `git grep DocumentKnowledgeGraphView nexus-console/` returns zero matches.
- `npm run typecheck`, `npm run lint`, `pytest nexus-app nexus-api` all pass.
- **Detector coverage sanity check**: manual review of ≥5 known theory-knowledge textbook assets confirms detector correctly classifies ≥80% as `theory_knowledge`. Sub-80% → open follow-up ticket (does NOT block this slice).

## Review Gate

- **DDL Review**: FK cascade behavior, index completeness, enum extension safety, downgrade path.
- **API Contract Freeze**: response shapes, error codes.
- **Atomic Replace**: dedicated test that a POST rebuild leaves no orphaned rows on the same `normalized_ref_id`.
- **Retirement Check**: `git grep DocumentKnowledgeGraphView` = 0, no orphan imports.
- **Screenshot Diff**: before/after on a `theory_knowledge` asset attached to PR.
- **Detector Coverage Note**: 5-sample manual review documented in PR description.

## Open Follow-ups (P1+)

- LLM-based knowledge-point extraction layered on outline nodes.
- Cross-node relations (`kg_edge` table) — prerequisite / related_to / example_of.
- Multi-textbook aggregation into a single outline graph.
- Outline diff view between rebuilds for editorial review.
- Extract `textbook_subtype` from `task_outline_profile` to a dedicated `textbook_profile` table if more textbook-scoped features arrive.
- Detector accuracy tuning if sample review reveals ≥20% gaps.
