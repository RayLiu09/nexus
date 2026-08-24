# Task Package: Crawler Low-Content Noise And Job-Demand Evidence Gate

## Source Context

- `AGENTS.md`: a governed asset must have usable normalized content and a
  traceable state; raw evidence is retained even when processing fails.
- `ARCHITECT.md`: crawler document acquisition enters Pipeline A, while AI
  governance is responsible for evidence-bound domain classification.
- `WORKFLOWS.md`: data-quality and governance changes require focused tests
  and auditable remediation of the identified asset.

## Goal

Prevent low-content crawler pages from becoming governed assets and prevent a
generic employment-site page from being classified as job-demand data without
actual job-record evidence.

## Scope

- Require a substantive Chinese body for non-PDF Firecrawl snapshots.
- Add a classification-prompt constraint: `job_demand` needs actual vacancy
  fields or enumerated job records, never source-site/domain inference.
- Mark asset `0882c6bf-c668-4153-8d95-ece64e7d9ad8` failed as crawler noise,
  with raw evidence retained and an audit event.
- Add focused regression tests.

## Out Of Scope

- Local topic relevance matching, query expansion, or LLM result relevance.
- Deleting raw objects, changing search-engine ranking, or reprocessing
  unrelated historical assets.

## Acceptance

- A 225-character crawler page is rejected as `too_short` before ingestion.
- A substantive document remains accepted without any topic comparison.
- The default classification prompt prohibits employment-site-only inference
  of `job_demand`.
- The identified asset is no longer available to asset processing or RAG and
  has an auditable failure reason.
