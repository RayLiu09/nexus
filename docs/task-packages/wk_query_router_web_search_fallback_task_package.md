# Task Package: Query Router WebSearch Fallback

## Status

Implementation in progress (2026-07-21).

## Source Context

- `docs/crawler_design_v1.0.md`: real-time AI WebSearch results are
  request-scoped, ungoverned public-web material and must never enter the
  asset, governance, chunk, or index paths.
- `ARCHITECT.md`: semantic retrieval and external providers are adapter-based;
  governed NEXUS assets remain the authoritative local retrieval source.
- `WORKFLOWS.md`: this changes internal and open Query Router response
  contracts and semantic retrieval behavior, requiring API Contract,
  Permission And Audit, and Semantic Retrieval Integration review.
- User decision (2026-07-21): for `scenario_1` and `scenario_4` only, a query
  with no usable local NEXUS asset evidence automatically falls back to
  real-time AI WebSearch. `scenario_2`, `scenario_3`, `scenario_5`, and
  `unknown` never invoke WebSearch.

## Goal

Return a clearly separated, request-only public-web result set when an
industry/report or textbook/general-knowledge query has no local asset
evidence, while preserving local results and preventing external content from
being mistaken for a governed NEXUS asset.

## Frozen Contract

1. Automatic WebSearch eligibility is exactly `scenario_1` or `scenario_4`
   plus an otherwise successful local dispatch with zero usable local evidence.
   It is not a replacement for dispatcher failure/unknown fallback.
2. `scenario_2`, `scenario_3`, `scenario_5`, and `unknown` must never invoke
   WebSearch, regardless of their local result count.
3. The external call receives only the user query after outbound-sensitive-data
   screening. It receives no local chunks, normalized references, user
   identity, session history, or permission information.
4. External results are response-only: no persistence, cache, ingestion,
   governance, index, LLM tool invocation, or generated NEXUS citation.
5. Provider failures, missing provider configuration, and blocked outbound
   queries leave the local answer intact and surface a stable warning.
6. Audit records only provider metadata, result count, domains, latency, and
   an error class; they never include external snippets, URLs in full, or the
   outbound query.
7. For `scenario_1` through `scenario_4`, zero usable local evidence is a
   deterministic terminal result. The Router must not invoke the Composer LLM:
   scenarios 1/4 may attach request-scoped WebSearch results; scenarios 2/3
   return their bounded no-data result locally.

## Scope

- Query Router result and audit metadata.
- Internal and open Query Router request/response schemas, including SSE final
  payloads.
- A provider adapter and configuration boundary for real-time AI WebSearch,
  with Firecrawl as the current configured provider and an extensible provider
  registry for later supported suppliers.
- Focused router, API, audit, and provider safety tests.
- `docs/crawler_design_v1.0.md`, `ARCHITECT.md`, `SPEC.md`, and `readme.md`
  contract updates for this user-approved automatic fallback.

## Out Of Scope

- WebSearch for structured data, professional data, graph queries, unknown
  queries, or scenario 5.
- Any external-result persistence, recrawl, download, ingestion, caching, or
  local index mutation.
- A Console visual redesign, crawler connector implementation, or new job
  infrastructure.

## Forbidden Changes

- Do not send sensitive/internal query material, local evidence, user identity,
  session history, or credentials to an external provider.
- Do not present external results as governed NEXUS assets or allocate NEXUS
  asset, normalized-ref, chunk, or citation identifiers to them.
- Do not bypass LiteLLM ownership for existing model routing or introduce an
  NEXUS LLM gateway.
- Do not invoke WebSearch as an `unknown` or generic dispatcher-failure
  fallback.

## Acceptance

- `最新AI智能体的发展趋势` classified as `scenario_1` with no local evidence
  invokes the WebSearch adapter and returns separated `external_web_results`.
- A no-hit `scenario_4` query behaves the same way.
- No-hit `scenario_2` and `scenario_3` queries do not invoke the adapter.
- A no-evidence result in each of `scenario_1` through `scenario_4` has
  `generated_ratio=0` and does not call the Composer LLM.
- Provider unavailability and sensitive-query blocks return the local result
  with warnings and no external result.
- Audit has no snippets, full URLs, or raw query, and reports provider metadata
  only.
- Focused `nexus-app` and `nexus-api` tests pass.
