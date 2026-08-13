# Task Package: Open External Search APIs

## Source Context

- `AGENTS.md`: externally consumed business APIs belong in `nexus-api`; API
  caller access is authenticated and auditable.
- `ARCHITECT.md` / `SPEC.md`: public-web results are request-scoped,
  non-governed material. They must not be persisted as raw objects, assets,
  normalized refs, governance results, knowledge chunks, or indexes.
- `docs/crawler_design_v1.0.md`: Firecrawl document acquisition and real-time
  WebSearch have separate contracts and must not be implicitly converted.

## Goal

Expose two explicit API-caller authenticated `/open/v1` external-search
endpoints: one for Firecrawl URL discovery and one for Web Search content
results. Preserve their materially different provider result shapes.

## Scope

- `nexus-api` read-only routes, Pydantic request/response contracts, and tests.
- Reuse the existing Firecrawl document-search client and WebSearch custom
  client only; do not add a provider or credential.
- Request-size bounds, outbound sensitive-query blocking, compact audit entries,
  trace propagation, and open API documentation.

## Out Of Scope

- Crawler plans, scraping, batch scrape, ingestion, assetization, normalization,
  governance, chunking, indexing, caching, and Console UI.
- A common provider-neutral response model or an automatic provider fallback.

## Forbidden Changes

- Do not write external results to `raw_object`, asset/domain tables,
  `normalized_asset_ref`, governance, chunks, embeddings, or indexes.
- Do not return provider credentials or log raw query text.
- Do not route these APIs through Query Router fallback behavior.

## Deliverables

- Two documented `/open/v1` endpoints with independent request/result shapes.
- Focused API contract tests for authentication, provider shape, blocked query,
  provider failure, and audit behavior.

## Acceptance

- Each endpoint requires `require_api_caller` and emits a compact search audit.
- Firecrawl and Web Search responses remain structurally distinct.
- Provider calls receive only the request query and declared controls.
- No external result is persisted beyond its access audit summary.
