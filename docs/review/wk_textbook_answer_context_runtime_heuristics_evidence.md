# Textbook Answer Context Runtime Heuristics Evidence

## Scope

- Runtime-only textbook answer context optimization.
- Single-asset outline rebuild for `短视频拍摄与剪辑.pdf`.
- No persisted chunk answerability fields.
- No migration.
- No full corpus rebuild.

## Target Asset

- `normalized_ref_id`: `94901be8-2a89-4d26-bc97-2b6ddc06ccb5`
- `asset_version_id`: `a9329d8c-76aa-4823-88d2-e4b67c018260`
- `title`: `短视频拍摄与剪辑.pdf`

## Pre-Rebuild Finding

The `六、白平衡` outline node was directly linked to 35 chunks. The direct
chunk set included the answer-bearing white-balance paragraphs, but also
task implementation text, ISO/EV/AF setup chunks, figure/UI OCR text,
reflection prompts, exercise questions, and later unrelated material.

## Rebuild

Command:

```bash
cd /home/bjbodao/projects/nexus/nexus-app
env PYTHONPATH=/home/bjbodao/projects/nexus/nexus-app \
  uv run python scripts/rebuild_knowledge_outline_for_ref.py \
  --ref-id 94901be8-2a89-4d26-bc97-2b6ddc06ccb5 --apply
```

Result:

- `textbook_subtype`: `theory_knowledge`
- `subtype_confidence`: `0.92`
- `build_run_id`: `35810314-015f-44b3-965a-622baee579d8`
- `total_nodes`: `402`
- `max_depth`: `3`
- `fallback_used`: `false`

## Post-Rebuild Finding

The `六、白平衡` outline node now links to 5 direct chunks instead of 35.
The remaining direct chunks are the three answer-bearing white-balance
paragraphs plus two structural/task-introduction chunks from the normalized
payload span. Runtime compact-answer heuristics filter the two structural
chunks for definition/method questions.

The existing `index_manifest(course_textbook)` remains `indexed` with
`chunk_count=1026`; this rebuild changed outline-node links, not chunk content
or chunk embeddings.

## Live Retrieval Verification

Query:

```text
什么是白平衡，如何调节
```

Executor arguments:

```json
{
  "query": "什么是白平衡，如何调节",
  "kb": "course_textbook",
  "top_k": 10,
  "similarity_threshold": 0.5
}
```

Observed result:

- `hits`: `7`
- `answer_contexts[0]`: `answer_span_context`
- `mode`: `compact_answer`
- `question_type`: `definition_with_method`
- compact answer chunks: `3`

Selected compact evidence:

- `a9ae48b6-cb13-4e9b-aaaf-4855387d3cb5`: white-balance definition and color-shift correction.
- `39493d73-c2e5-4378-9ed3-f6e5fe6c42ea`: preset/manual/automatic white-balance adjustment modes.
- `da314172-23c9-41b4-8178-de96823838ac`: manual white balance, color temperature, warm/cool direction, and common range.

Excluded from compact answer:

- ISO setup.
- EV setup.
- AF/focus setup.
- figure/UI OCR chunks.
- task reflection and exercise chunks.
- Premiere/HSL/curve/vignette chunks.

## Tests

```bash
cd /home/bjbodao/projects/nexus/nexus-app
uv run pytest tests/retrieval/test_tool_executors_v2.py tests/retrieval/test_composer_v2.py
```

Result:

```text
62 passed
```

```bash
cd /home/bjbodao/projects/nexus/nexus-api
uv run pytest tests/test_query_router_v2_endpoints.py
```

Result:

```text
8 passed
```

## Review Gate Notes

- Semantic Retrieval Integration Gate: citations remain chunk/ref based.
- The pgvector adapter remains the retrieval backend.
- Complete section contexts are still available when explicitly selected by
  question mode.
- Definition/method textbook questions now use compact runtime context and do
  not force full-section deterministic rendering.
