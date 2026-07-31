# Pipeline-Owned Knowledge Outline Build Evidence

## Change Summary

- Added `run_knowledge_outline_build` as a best-effort pipeline stage.
- Wired the stage into both normal document knowledge execution and human-review
  knowledge continuation, immediately after `run_knowledge_chunking` and before
  `run_index_submit`.
- The stage:
  - skips non-document refs;
  - skips refs without chunks;
  - skips non-`course_textbook` refs;
  - skips refs that already have outline rows;
  - loads the normalized payload from object storage;
  - reuses existing `task_outline_profile` without overwriting it;
  - detects textbook subtype only when no profile exists;
  - creates `task_outline_profile` only for eligible refs that lack one;
  - builds `knowledge_outline_node` for `theory_knowledge` / `hybrid`;
  - records failures as non-blocking `knowledge_outline_build` job-stage rows.

## Risk Controls

- No retrieval code was changed.
- No vector search or index adapter code was changed.
- No schema migration was added.
- The stage is non-blocking: failures do not prevent existing chunking and
  index submission from proceeding.
- Existing outline construction/backfill service is reused instead of adding a
  second implementation.
- Existing non-eligible task-outline profiles are not overwritten.

## Verification Commands

```bash
uv run pytest tests/governance/test_pipeline_integration.py -k KnowledgeOutlineBuildStage
```

Result:

```text
2 passed, 20 deselected
```

```bash
uv run pytest tests/knowledge_outline/test_service.py
```

Result:

```text
14 passed
```

Additional retrieval safeguards after section ranking and answer-span
enumeration expansion:

```bash
uv run pytest tests/retrieval/test_textbook_qa_golden.py
```

Result:

```text
7 passed
```

```bash
uv run pytest tests/retrieval/test_tool_executors_v2.py tests/retrieval/test_composer_v2.py
```

Result:

```text
63 passed
```

```bash
uv run pytest tests/test_query_router_v2_endpoints.py
```

Result:

```text
8 passed
```

Manual E2E verification after targeted rebuild of
`1d2ec59f-057a-4da7-843d-5600e200b05e`:

- Query: `现代零售行业的关键特征是什么`
- `section_contexts[0].title`:
  `知识点1：现代零售行业的四大关键特征`
- Final markdown includes:
  - `全渠道深度融合`
  - `数据驱动精细化运营`
  - `用户体验`
  - `即时化履约`
- Final markdown excludes:
  - `老师：`
  - `课后`
  - `根本准则`
