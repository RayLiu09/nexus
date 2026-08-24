# Task Package: Crawler Query Scope And Query Integrity

## Source Context

- `AGENTS.md`: crawler inputs must preserve truthful lineage; public assets
  must not expose unrelated available data under a domain-specific plan.
- `ARCHITECT.md`: crawler content enters Pipeline A as a document only after
  source acquisition and normalization; governance is not a search-relevance
  classifier.
- `WORKFLOWS.md`: crawler acceptance and asset admission require focused
  tests and a Version State review for historical remediation.

## Goal

Make a Firecrawl plan preserve the user's search terms and derive its recorded
search scope from those terms, without local topic expansion or relevance
classification.

## Scope

- Resolve province scope from query text, recording `national` only when no
  province is specified.
- Preserve explicit user search terms without template-added broad OR terms.
- Keep generic web quality checks limited to accessibility/content validity;
  provider `RankScore` is not an NEXUS admission threshold.
- Add focused tests and document the boundary.

## Out Of Scope

- LLM relevance evaluation, semantic query expansion, local topic matching,
  or governance-stage relevance checks.
- Generic search-provider ranking changes and automatic historical cleanup.

## Forbidden Changes

- Do not add broad keywords not present in the plan/query.
- Do not move relevance decisions into the quality gate, AI governance, or
  domain extraction.
- Do not filter results by provider ranking score after the provider has
  returned them.

## Acceptance

- A query containing `江苏` records a Jiangsu scope; an unspecified query
  records a national scope.
- A user-provided query is passed to Firecrawl without template broadening.
- Generic quality-gate tests continue to cover access/noise validation
  independently of search relevance.
