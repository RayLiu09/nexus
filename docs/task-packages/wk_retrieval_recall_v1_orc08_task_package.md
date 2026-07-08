# Task Package: ORC-08 Internal Knowledge Retrieval API

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-08 exposes the v1.0 retrieval/recall orchestration API for Console use.
- `nexus_app.retrieval.orchestrator`: intent -> plan -> retrieval -> context pack.
- `nexus_app.retrieval.summary`: evidence-bound Markdown summary generation.
- `nexus_api.api.internal`: `/internal/v1` Console control-plane API router guarded by `require_user`.

## Goal

Expose internal Console APIs for executing the v1.0 retrieval/recall flow and previewing retrieval plans.

## Scope

- Add `POST /internal/v1/knowledge-retrieval/query`.
- Add `POST /internal/v1/knowledge-retrieval/plans`.
- Return the full context pack shape required by Console: status, intent, plan, retrieval results, conversation steps, Markdown, source refs, and `access_scope`.
- Use fake orchestrator/summary services in API tests; no real LLM, embedding, or vector calls.
- Keep existing `/open/v1/search` and `/open/v1/qa` contracts unchanged.

## Out Of Scope

- Console UI implementation.
- SSE or realtime step events.
- Productized audit persistence.
- Permission filtering; v1.0 keeps `access_scope = all_assets`.
- New retrieval executors or structured domains.
- Database migrations.

## Forbidden Changes

- Do not expose this as an external `/open/v1` business API.
- Do not call model providers directly; use `nexus_app.retrieval` services.
- Do not persist query plaintext, answer Markdown, Prompt text, source content, or API keys.
- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not change `/open/v1/search` or `/open/v1/qa` behavior.

## Deliverables

- `nexus-api/nexus_api/api/internal/knowledge_retrieval.py`
- `nexus-api/nexus_api/api/internal/__init__.py`
- `nexus-api/tests/test_knowledge_retrieval_api.py`
- Optional response schema additions in `nexus-api/nexus_api/schemas.py` if needed.

## Acceptance

- High-confidence query API returns a completed context pack with Markdown and source refs.
- Low-confidence query API returns `needs_clarification` and no Markdown.
- Plans API returns intent + retrieval plan without running summary generation.
- API tests use fake services and do not perform network calls.
- `/open/v1/search` and `/open/v1/qa` regression tests are not affected.
