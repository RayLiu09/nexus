# Task Package: Asset Center Initial Load

## Source Context

- `ARCHITECT.md` and `SPEC.md`: Asset Center counts remain real, on-demand
  business and catalog aggregates.
- Prototype v2.2 section 4.1A: four visible domain cards link directly to
  resource views; an API failure must not appear as a zero count.
- `WORKFLOWS.md`: bounded Console UX change with Frontend UX Gate review.

## Goal

Make Asset Center resource links usable while the aggregate count request is
still running, without changing count semantics or the internal API.

## Scope

- `/asset-center` page rendering and the overview count loading state.
- Focused frontend tests and verification.

## Out Of Scope

- Count persistence, caching, new APIs, data model changes, and resource lists.

## Forbidden Changes

- Do not replace real counts with mock values or treat request failures as zero.
- Do not change governance, version selection, or domain projection ownership.
- Do not introduce IAM or a NEXUS LLM gateway.

## Acceptance

- The header and four linked domain cards render before the counts API resolves.
- Pending counts say loading; failed counts say unavailable; successful counts
  retain the current values and links.
- Frontend tests, typecheck, and Frontend UX Gate review pass.
