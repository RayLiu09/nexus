# Task Package: Public Tools Chat Phase 1

## Status And Goal

Implementation and focused verification complete (2026-11-05); human Review Gates pending before merge. Delivered model-selected public business queries, full-set aggregates, evidence completion, source-linked web fallback and a streaming Chatbot Console.

## Source Context

- User-approved `docs/intelligent_search_phase1_technical_plan.md` and environment configuration slice.
- `ARCHITECT.md`, `SPEC.md`: public API contracts, LiteLLM routing and versioned `ai_prompt_profile`.
- Prototype v2.2 NX-11: intelligent retrieval, visible sources and permission boundaries.
- `WORKFLOWS.md`: API, AI Governance, Semantic Retrieval, Permission/Audit and Frontend UX review before merge.

## Scope / Ownership

Single agent. Allowed: new public-tool runtime/executor in `nexus-api`, internal query wiring and SSE, shared result/event fields, new retrieval Prompt seeds/validation and boot initialization, query UI and proxy, Prompt scenario registry, focused tests/dependencies/lockfiles, architecture/spec/readme/prototype/evidence docs. Preserve unrelated governance-review edits and task artifacts.

## Frozen Contracts

- Reuse existing query and stream paths; internal Console uses the new runtime, external query compatibility remains on the existing router. No per-tool HTTP routes.
- Generate catalog from application OpenAPI using the existing generator. All current business, aggregate and evidence tools registered; exclude nested query/QA and raw download URL tools. Dynamic model selection uses stage-specific subsets: primary business/discovery tools, then the complete evidence subset.
- HTTP executor uses fixed server-configured origin, generated method/path only, full JSON Schema validation, path quoting/repeated query arrays, no redirects, bounded response size/time. Key from `BUILDIN_API_CALLER` never enters model or UI. No SQL generation.
- Console login remains required; real user audited on query, API caller audited by public services, common trace ID. Existing open:* organization filtering is a documented P0 noop; no new isolation claims.
- `INGEST_SEARCH_RESULTS` overrides search auto_ingest; default false. True queues through existing ingestion gates, never directly publishes assets.
- Bounded stages: resource discovery and primary query (up to two model rounds, at most eight local calls), evidence supplementation (one round, at most three calls), up to three deterministic source-driven evidence reads, optional one web search, evidence-based answer; at most 16 HTTP tool calls total. No persisted conversation or autonomous unbounded agent.
- No-hit/low-score or explicit model evidence insufficiency can trigger web; explicit local-only scope prevents it; errors distinguished from empty. Never send sensitive query/body or internal evidence to search providers.
- Sources are registered from actual successful results: documents, records, aggregates and external web remain distinct. Citation IDs validated after generation; source records carry locating identifiers and query scope. Answer references use [N] and source UI.
- SSE preserves existing event names; step IDs dynamic, action lifecycle includes cancellation, request/turn/event sequence context included. Disconnect cancels subsequent work; in-flight synchronous requests bounded by timeouts.
- Frontend uses Ant Design X 2.10.0 (peers match antd6/React19), existing Markdown renderer and SSE. Native chat layout, live collapsible actions, source detail, stop, error/no-data/partial states; history is page-local, each query independently executed in phase 1.
- User refinements: full available page width; sources collapsed by default; human-readable excerpts/filter labels, no UUIDs/internal keys/raw JSON in source details; Enter sends, Shift+Enter inserts newline, IME composition does not submit. Sender's own SendButton keeps keyboard submission state synchronized.
- Welcome content (heading, description and suggested questions) is horizontally centered and vertically centered slightly above the conversation-area midpoint, with responsive spacing and a bottom composer.

## Forbidden / Out Of Scope

No new IAM/gateway/queue, no schema migration, no arbitrary external URL execution, no raw file exposure, no automatic available status, no semantic index rewrite, no persistent multi-turn orchestration. Do not log credentials, sensitive/plain raw bodies or queries. Do not change caller grants or fabricate citation/relevance metrics.

## Acceptance And Review Evidence

- Tests: generated catalog coverage/validation, fixed-origin HTTP serialization/secret and ingestion policy, revoked/failed calls, low-score and no-hit web, local-only, evidence binding and citations, bounded execution/cancellation, SSE compatibility and audit actor.
- UI: typecheck, targeted Vitest including cancellation/truncated stream/stale events/source interactions, browser preview with deterministic network fixtures and appropriate live read-only smoke checks.
- Generator drift check; quality comparison reported as fixture evidence, not proof of live quality uplift.
- Evidence and limitations recorded here and in review document before completion; relevant human Review Gates remain required before merge.

Verification: API focused suite 62 passed, plus final runtime suite 15 passed after budget hardening (63 unique API tests total); app configuration/LiteLLM/stream/web-search suite 69 passed; frontend 37 passed and TypeScript check passed; Playwright desktop/tablet 6 passed including 1920px and 390px layout checks and keyboard regression. Generated function-tool drift check passed. Real read-only model queries completed in 31.90s / 40.62s with 1 / 40 sources and no runtime warnings. No ingestion was performed. See [review evidence](../review/query_public_tools_chat_phase1_review.md) for commands, scope and limitations. No commit, push or merge in this task.
