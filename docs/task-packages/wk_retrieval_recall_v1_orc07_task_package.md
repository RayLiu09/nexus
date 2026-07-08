# Task Package: ORC-07 Retrieval Markdown Summary

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-07 generates a Markdown summary from the context pack evidence set.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: the fourth layer must only summarize facts supported by retrieval results and source refs.
- `nexus_app.retrieval.schemas`: `RetrievalContextPack` and `LlmSummary` contracts.
- `nexus_app.ai_governance.litellm_client`: LiteLLM gateway client boundary.

## Goal

Add the v1.0 summary generation layer that converts retrieval evidence into a user-facing Markdown result while preserving source-ref traceability.

## Scope

- Add prompt construction for summary generation.
- Add `RetrievalSummaryService`.
- Validate that returned `source_ref_ids` exist in the context pack.
- Return a deterministic no-evidence summary without calling LLM.
- Add tests with fake LiteLLM clients.

## Out Of Scope

- Orchestrator integration.
- API integration.
- Console integration.
- Prompt profile database seeding.
- Audit persistence.
- Rerank, citation enrichment, or additional retrieval.

## Forbidden Changes

- Do not call model providers directly; use LiteLLM client boundary.
- Do not let LLM invent source refs outside the context pack.
- Do not persist user query text, answer Markdown, Prompt text, source content, or API keys.
- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not change `/open/v1/search` or `/open/v1/qa` contracts.

## Deliverables

- `nexus-app/nexus_app/retrieval/summary.py`
- `nexus-app/nexus_app/retrieval/prompts.py`
- `nexus-app/tests/retrieval/test_summary_generation.py`
- Export updates in `nexus-app/nexus_app/retrieval/__init__.py`.

## Acceptance

- Fake LLM Markdown output is accepted when all cited `source_ref_ids` exist in the context pack.
- Fake LLM output with unknown `source_ref_ids` is sanitized and produces warnings.
- No-evidence context packs return “未检索到足够依据” and do not call LLM.
- Invalid JSON or LiteLLM errors return a deterministic safe summary with warnings.
- Prompt payload includes evidence summaries and source refs, but does not include API keys or Prompt internals.
