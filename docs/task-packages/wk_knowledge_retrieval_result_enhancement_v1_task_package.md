# Task Package: Knowledge Retrieval Result Enhancement v1.0 Design

## Source Context

- `AGENTS.md`: retrieval must preserve NEXUS architecture boundaries, no self-developed `llm-gateway`; use existing LiteLLM for LLM calls when implementation follows.
- `ARCHITECT.md`: `search-service` owns retrieval orchestration; semantic retrieval backend is adapter-selected; P0 default is pgvector behind the adapter; `knowledge_chunk.normalized_ref_id` links chunks to normalized refs; external index backend ids do not live on chunks.
- `SPEC.md`: search/QA must be traceable to normalized refs/chunks/source citations and auditable; v1.0 retrieval design temporarily defaults to all-assets access.
- `docs/knowledge_retrieval_result_enhancement_draft.md`: v0.2 discussion draft for intent routing, structured/unstructured channels, and context pack.

## Goal

Produce a v1.0 design document for NEXUS knowledge/data-asset retrieval result enhancement based on the latest discussion conclusion:

1. LLM intent recognition maps user intent to platform data domains.
2. LLM query transformation may split/rewrite the user question into multiple retrieval questions.
3. Each transformed query is retrieved in parallel.
4. LLM summarizes retrieval/recall results into a structured Markdown response.
5. Intent recognition confidence below 0.78 pauses retrieval and asks the user whether they want to refine the question.
6. Console retrieval conversations display intent analysis, retrieval plan, and multi-step execution progress as user-visible auxiliary analysis.

## Scope

- Add a v1.0 design document under `docs/`.
- Preserve v0.2 draft as historical input.
- Clarify structured versus unstructured retrieval execution paths.
- Clarify SQL generation/query safety boundaries for structured domain tables.
- Clarify low-confidence clarification behavior.
- Clarify Console multi-step real-time interaction behavior.
- Clarify that v1.0 defaults to all-assets access and does not implement permission scoping.
- Clarify LLM responsibilities and non-responsibilities.

## Out Of Scope

- Code implementation.
- Database migrations.
- Public `/v1` API contract freeze.
- Frontend UI implementation.
- Implementing the pgvector adapter or selecting the post-P0 replacement semantic retrieval backend.
- Permission/governance filtering implementation details beyond design constraints.
- Implementing Console UI code.

## Forbidden Changes

- Do not introduce a self-developed `llm-gateway`; implementation must route model calls through LiteLLM.
- Do not make raw files, raw JSON, or MinerU output valid governance or retrieval governance inputs.
- Do not make `knowledge_chunk` the retrieval model for all structured record assets.
- Do not let LLM-generated SQL execute without domain schema whitelist, parameterization, and query guardrails.
- Do not persist answer plaintext or query plaintext into audit logs.
- Do not automatically execute retrieval when intent confidence is below 0.78 unless the user confirms continuing or refines the question.

## Deliverables

- `docs/knowledge_retrieval_result_enhancement_v1.0.md`

## Acceptance

- The design explicitly contains the four-layer retrieval/recall flow.
- The design distinguishes unstructured retrieval from structured SQL domain-table retrieval.
- The design explains how LLM organizes unstructured snippets and structured query outputs into Markdown.
- The design names pgvector as the P0 default semantic retrieval adapter while preserving NEXUS adapter, traceability, and audit boundaries.
- The design states that intent recognition results are shown to users as auxiliary analysis in the retrieval conversation.
- The design states that retrieval plans are shown to users as auxiliary analysis in the retrieval conversation.
- The design states that intent confidence below 0.78 returns a clarification/refinement interaction before automatic retrieval.
- The design states that v1.0 assumes all assets are accessible and defers permission scoping.
- The design defines multi-step Console interaction states for intent recognition, query transformation, parallel retrieval, context assembly, and summary generation.
