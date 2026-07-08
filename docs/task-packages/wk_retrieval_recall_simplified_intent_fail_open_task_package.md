# Task Package: Retrieval Recall Simplified Intent Fail-Open

## Source Context

- User feedback: current intent recognition is too complex and blocks retrieval when the intent schema is invalid or the model result does not match strict schemas.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: intent recognition should map user questions to platform data asset domains and expose auxiliary analysis to users.
- `nexus_app.retrieval.intent`: current implementation treats low confidence or schema-invalid intent as a blocking clarification context pack.
- `nexus_app.retrieval.orchestrator`: current implementation returns failed context packs when retrieval plan generation fails.

## Goal

Simplify retrieval/recall v1.0 runtime behavior so intent recognition narrows data asset domains but never blocks basic retrieval. Query transformation should improve recall precision when possible, while failures fall back to the original user question.

## Scope

- Make intent recognition fail open:
  - low confidence returns a fallback intent and warning rather than blocking retrieval;
  - schema-invalid or LiteLLM call failures return a fallback intent and warning rather than `needs_clarification`.
- Keep intent analysis visible in Console as auxiliary analysis.
- Make retrieval plan generation fail open at orchestrator level:
  - when planner schema validation fails, build a minimal unstructured fallback plan from the original user question and recognized/fallback unstructured domains.
- Keep explicit clarification data as suggestions only, not an automatic blocker.
- Update focused backend tests.

## Out Of Scope

- Adding new retrieval executors for all platform data asset types.
- Database migrations.
- SSE or realtime backend execution events.
- Changing `/open/v1/search` or `/open/v1/qa`.
- Productized permissions; v1.0 still uses `access_scope=all_assets`.

## Forbidden Changes

- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not execute raw SQL from LLM output.
- Do not persist query plaintext, prompt text, model output text, source content, or API keys.
- Do not loosen executor guardrails for structured retrieval.
- Do not make intent recognition a hard gate for retrieval.

## Deliverables

- Backend intent recognition fail-open behavior.
- Backend fallback retrieval plan construction.
- Prompt update that frames intent recognition as asset-domain narrowing.
- Tests proving low-confidence/schema-invalid/planner-invalid flows still return executable retrieval plans.

## Acceptance

- Low-confidence intent recognition produces warnings but retrieval continues.
- Invalid intent JSON/schema produces warnings but retrieval continues with default broad unstructured domains.
- Invalid retrieval plan schema produces warnings but retrieval continues with a fallback unstructured plan.
- Console can display warnings/diagnostics without losing retrieval results.
