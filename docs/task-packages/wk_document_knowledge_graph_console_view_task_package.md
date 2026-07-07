# Task Package: Document Knowledge Graph Console View

## Task name

Add a document-level knowledge graph view in Asset Detail -> 知识块.

## Source context

- `ARCHITECT.md`: `knowledge_chunk` and normalized content are NEXUS-owned
  read models linked to `normalized_asset_ref`; console APIs are internal
  control-plane APIs.
- `SPEC.md`: Asset detail exposes chunks, source traceability, and knowledge
  asset inspection without changing external search/QA contracts.
- `WORKFLOWS.md`: UI/API changes should be bounded and avoid cross-cutting
  rewrites.
- `docs/task-packages/wk_rag_chunk_console_semantic_context_task_package.md`:
  chunk-level knowledge graph is console-only and independent from
  `/open/v1/search`.

## Goal

Let console users inspect the whole textbook/document hierarchy between
RAG知识块 and Evidence Graph as a document-level graph:

```text
文档标题 -> 章/模块 -> 节
```

The graph intentionally does not render finer-grained knowledge point content,
and should focus on the document's overall knowledge outline rather than
paragraph-level detail.

## Scope

- Add a `知识图谱` segmented view in `DocumentKnowledgeView`.
- Build a document-level graph from existing normalized content blocks via the
  existing `/api/normalized-refs/{refId}/content` proxy.
- Render an ECharts horizontal tree with title/chapter/section levels only.
- Render a pure graph canvas without a right-side content/detail panel.
- Reuse existing console-only normalized content API; no new backend endpoint is
  required for this slice.

## Out of scope

- `/open/v1/search` changes.
- `/open/v1/qa` changes.
- Evidence Graph build/runtime changes.
- New persistent document section tree tables.
- Rendering paragraph-level knowledge points in the document graph.

## Forbidden changes

- Do not expose this console-only graph through external APIs.
- Do not read raw files or MinerU raw output directly.
- Do not add reverse pointers to asset/version/ref/chunk tables.
- Do not change the Evidence Graph persistence model.

## Deliverables

- Console document knowledge graph component.
- Asset detail `知识块` tab view switch update.
- TypeScript verification evidence.

## Acceptance

- The `知识块` tab shows `RAG知识块 -> 知识图谱 -> Evidence Graph` order when
  Evidence Graph is available.
- The new `知识图谱` view displays a three-level title/chapter/section graph for
  document normalized refs.
- The graph focuses on the whole-document knowledge outline and does not expose
  paragraph/block detail panels.
- The graph does not render lower-level knowledge point nodes.
- Existing chunk preview and Evidence Graph views remain available.

## Verification

```bash
cd nexus-console
npm run typecheck
```
