# Task Package: ORC-02 LiteLLM Intent Recognition

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-02 adds the LLM intent recognition layer after ORC-01 schema and registry.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: intent recognition maps user questions to platform domains/channels and blocks automatic retrieval when confidence is below 0.78.
- `AGENTS.md`: model calls must go through LiteLLM; prompt management belongs to NEXUS.
- `nexus_app.retrieval.schemas`: ORC-01 contracts for `RetrievalIntent`, `ConversationStep`, `Clarification`, and `RetrievalContextPack`.

## Goal

Implement the first retrieval orchestration runtime layer: LiteLLM-backed intent recognition with schema validation and low-confidence clarification handling.

## Scope

- Add retrieval intent prompt construction.
- Add an `IntentRecognitionService` that calls LiteLLM chat completion through the existing client protocol.
- Parse and validate LLM JSON into `RetrievalIntent`.
- Return completed intent step for high-confidence output.
- Return `needs_clarification` context pack for confidence below the configured threshold.
- Return failed/clarification-safe output for schema-invalid or non-JSON model output.
- Add focused tests using fake LLM clients.

## Out Of Scope

- Query transformation / retrieval plan generation.
- pgvector or structured SQL execution.
- Orchestrator wiring.
- Internal API wiring.
- Console UI.
- Prompt profile persistence or seeding.

## Forbidden Changes

- Do not call model providers directly; use the existing LiteLLM client protocol.
- Do not execute retrieval from this layer.
- Do not persist user query text or model response text into audit logs.
- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not loosen ORC-01 schemas to accept arbitrary domains/channels.

## Deliverables

- `nexus-app/nexus_app/retrieval/prompts.py`
- `nexus-app/nexus_app/retrieval/intent.py`
- `nexus-app/tests/retrieval/test_intent_recognition.py`
- Settings additions for retrieval intent model alias and confidence threshold.

## Acceptance

- High-confidence fake LLM output returns `status=completed` and an `intent_recognition` completed step.
- Low-confidence fake LLM output returns `status=needs_clarification`, a clarification message, and no retrieval plan.
- Invalid JSON/schema-invalid fake LLM output returns a safe failed/clarification result without an unhandled exception.
- Prompt payload includes domain registry information and does not include credentials.
- Tests perform no network calls.

