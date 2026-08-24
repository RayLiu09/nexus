# Task Package: PDF Candidate Integrity Gate

## Source Context

- `AGENTS.md`: raw objects and downstream governance must preserve truthful
  lineage; only normalized content may enter governance and knowledge flows.
- `ARCHITECT.md`: PDF document input follows the MinerU document path; crawler
  content must retain its real representation and source evidence.
- `WORKFLOWS.md`: crawler state, asset version state, and public data quality
  are subject to the Version State and Semantic Retrieval Integration gates.

## Goal

Prevent a crawler PDF candidate whose original binary download fails from
becoming an available document asset based only on a Firecrawl snapshot.

## Scope

- Preserve PDF download failure diagnostics in `crawler_run.summary`.
- Treat failed PDF-candidate download as an ingest failure with no raw object,
  asset version, normalization, governance, or index job submission.
- Cover the behaviour with crawler tests.
- Reclassify the known fallback asset only after confirming its replacement
  cannot be rebuilt from a real PDF in the current run.

## Out Of Scope

- Changing non-PDF web-document ingestion.
- Persisting Firecrawl fallback text as a separate product asset.
- Circumventing source-site restrictions, bypassing URL safety, or adding a
  new crawler provider.

## Forbidden Changes

- Do not label fallback Markdown/HTML as `application/pdf`.
- Do not let a failed PDF candidate enter available governance or RAG.
- Do not delete raw evidence or alter unrelated assets.

## Deliverables

- Crawler integrity-gate implementation and tests.
- Existing fallback-asset remediation with audit evidence when applicable.

## Acceptance

- A PDF download failure creates no document asset/job for that candidate.
- The CrawlerRun is `partial_failed` (or `failed` when nothing else succeeds)
  and records the reason and candidate URL.
- A successful PDF still enters as `application/pdf` and uses the normal
  document path.
