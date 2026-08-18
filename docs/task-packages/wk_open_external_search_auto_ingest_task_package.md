# Task Package: Open External Search Auto Ingest

## Goal

Allow qualifying results from the public Firecrawl and Web Search endpoints to
enter the existing crawler document ingest pipeline automatically.

## Source Context

- `ARCHITECT.md`: crawler documents use Pipeline A and must pass through raw
  persistence, assetize, parse, normalize, governance, and indexing.
- `SPEC.md`: Firecrawl HTML uses the deterministic main-content extractor;
  job failures and ingest actions must be auditable.

## Scope

- `/open/v1/external-search/firecrawl` and `/open/v1/external-search/web-search`.
- `auto_ingest` request flag, defaulting to enabled; disabled requests remain
  search-only and must not create crawler inputs.
- Existing `evaluate_snapshot` and `evaluate_websearch_item` quality gates.
- Existing crawler data sources, batch ingestion, and queued jobs.
- Focused API tests and response/audit summaries.

## Out Of Scope

- New public write endpoints, database migrations, synchronous Worker
  execution, or bypassing governance/index admission.
- Persisting external query text or external result bodies in search audit logs.

## Acceptance

- Only existing quality-gate accepted results produce raw objects and queued
  Pipeline A jobs.
- Web Search raw-object filenames include a safe result title plus content hash
  so the raw-data ledger is meaningful to operators.
- Response exposes accepted, filtered, submitted, and duplicate counts without
  exposing audit-sensitive prose.
- Stable result identity makes repeated provider results idempotent.
