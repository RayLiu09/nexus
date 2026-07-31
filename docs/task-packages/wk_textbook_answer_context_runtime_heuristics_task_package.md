# Task Package: Textbook Answer Context Runtime Heuristics

## Source Context

- `AGENTS.md`: Knowledge Pipeline remains independent, retrieval results must
  trace to `normalized_asset_ref` and `knowledge_chunk`; do not introduce raw
  governance inputs or new retrieval backends.
- `ARCHITECT.md`: Query Router v2 may expand textbook evidence into complete
  chapter contexts, while `/open/v1/search` remains compact chunk evidence.
- `SPEC.md`: Search/QA must preserve citations, audit, permission filtering,
  and source traceability.
- Current retrieval behavior: textbook `section_context` expansion can return
  all chunks linked to an outline node, and Composer may render those chunks
  directly without LLM summarization.

## Goal

Improve smart retrieval answer precision for regular textbook questions by
selecting runtime answer context according to question type, so definition,
method, parameter, and comparison questions receive compact cited evidence
instead of full chapter spillover.

## Scope

- Add runtime-only textbook question classification and chunk evidence scoring.
- Build compact `answer_span_context` from semantic hits and selected section
  contexts for definition/method-style questions.
- Keep complete `section_context` available for explicit chapter/full-content
  questions.
- Update Composer to prefer `answer_span_context` and to render complete
  sections only when the context declares `mode=complete_section`.
- Add focused regression tests, including "what is X and how to adjust/use it"
  style questions, without hard-coding the "white balance" topic.

## Out Of Scope

- New database fields, migrations, or persisted chunk answerability tags.
- New retrieval backend, mandatory LLM rerank, or gateway changes.
- Full historical rebuild.
- Changing `/open/v1/search` response schema.
- Productized data repair workflow.

## Data Repair Boundary

If historical data repair is needed for verification, rebuild only the
`短视频拍摄与剪辑` course-textbook asset and its corresponding chunks/index
manifest. Do not rebuild all textbook assets.

## Forbidden Changes

- Do not hard-code topic-specific branches such as `if "白平衡" in query`.
- Do not persist runtime evidence roles to `knowledge_chunk`.
- Do not make raw files, raw JSON, or MinerU raw output valid retrieval inputs.
- Do not reintroduce RAGFlow as the semantic retrieval baseline.
- Do not remove source citations or audit-ready chunk/ref identifiers.

## Deliverables

- Runtime heuristic code.
- Composer rendering gate update.
- Focused tests for compact answer context and complete section preservation.
- Verification command output or documented test result.

## Acceptance

- A definition + method textbook query returns a compact `answer_span_context`
  with cited core/supporting chunks and excludes exercise/UI/sibling-topic
  chunks.
- Explicit full-section questions still render complete section contexts.
- Procedure questions still render ordered `task_context` steps.
- The implementation is topic-general and can handle future regular textbook
  questions such as sensitivity, exposure compensation, focusing mode, HSL, and
  three-point lighting.

## Review Gate

- Semantic Retrieval Integration Gate: source citations remain anchored to
  existing chunks, complete-section behavior is preserved when explicitly
  requested, and the pgvector adapter remains the retrieval backend.
