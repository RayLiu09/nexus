# Semantic Retrieval Context Recall Fix Evidence

## Scope

- Task package: `wk_retrieval_semantic_context_recall_fix_task_package.md`.
- Runtime-only retrieval enrichment. No migration, external API schema change,
  raw-content read, or vector backend replacement.

## Semantic Retrieval Integration Gate

- First-stage retrieval remains `PgvectorSearchAdapter.search`.
- The new assembler reads only NEXUS-owned `knowledge_chunk`,
  `knowledge_outline_node`, and `task_outline_node` rows.
- Every expanded item preserves `chunk_id`, `locator`, and
  `source_block_ids`; original vector hits remain unmodified in `hits`.
- Expansion is bounded to three refs, 24 theory-section chunks, or 24 task
  operation steps.

## Regression Evidence

```text
cd nexus-app
uv run pytest tests/retrieval/test_tool_executors_v2.py tests/retrieval/test_router_v2.py tests/retrieval/test_router_v2_stream.py tests/retrieval/test_composer_v2.py -q
60 passed

cd ../nexus-api
uv run pytest tests/test_search_qa_outline_fusion.py tests/test_search_qa_audit.py -q
15 passed
```

Focused cases verify that:

1. a learning-objective vector hit for `短视频平台的类型` expands to the
   query-matched section instead of the stale preceding-section association;
2. a `市场数据采集流程是什么` task hit expands to operation steps in document
   order.
3. Composer receives a runtime policy requiring `answer_contexts` to be used
   for classification and procedure answers rather than treating a weak flat
   hit as proof that the asset has no answer.
4. explicit `outline_node` is translated to subtree `chunk_ids` before
   pgvector ranking, while an automatically resolved scope fails open only
   when scoped vector retrieval is empty.
5. Router `unknown_fallback` first retrieves broadly, then resolves an
   outline only inside its hit refs and performs the same scoped second pass;
   it no longer sends flat hits directly to Composer.
6. Automatic outline resolution is disabled for non-textbook KBs. The
   canonical default public textbook KB is `course_textbook`; `textbook_kb`
   remains an explicit legacy compatibility value.

## Development Data Verification

Read-only verification against the development database produced:

- `94901be8-2a89-4d26-bc97-2b6ddc06ccb5` + hit
  `9c88ed5c-1081-48ba-adb7-226d840be47a`:
  `section_context` title `一、短视频平台的类型`, five cited chunks.
- `be6079d7-4ac8-43c3-b182-3558bb7344de`:
  `task_context` title `工作任务一 市场数据采集`, ten cited operation-step
  chunks across its two work subtasks. Each context item now includes its
  subtask title when step numbering restarts.

Two-stage pre-search scope verification additionally produced:

- `短视频平台的类型` -> `knowledge_outline` node
  `7f9c5265-6d96-4140-8c57-c7f0343ac2dd`, five candidate chunks.
- `市场数据采集流程是什么` -> `task_outline` node
  `node-task-6b4c72329d28`, ten `operation_step` candidate chunks (the task
  subtree's non-step chunks are excluded before vector ranking).
- The same explicit short-video outline node is `mandatory=true`; no broad
  fallback is allowed for a caller-selected scope.

## Residual Risk

Some historical `knowledge_outline_node_id` links remain incorrectly assigned
because old backfill used first source-block intersection. The runtime
query-title selection avoids that bad relation for title-matching requests.
A separate, audited rebuild/backfill task is still required to repair all
historical outline associations; it is intentionally outside this runtime-only
retrieval fix.

## Static Analysis

`uv run ruff check ...` could not run because `ruff` is not installed in the
project environment. This is an environment/tooling gap, not a reported lint
violation.
