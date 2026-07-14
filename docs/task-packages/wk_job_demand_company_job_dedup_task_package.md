# Task Package: Job Demand Company-and-Role Data Cleaning

## Source Context

- `AGENTS.md`: asset pipeline stages remain distinct and mutations must be
  auditable; Pipeline B raw records remain traceable through normalized assets.
- `docs/pipeline_b_b4_b6_contract_freeze.md`: B4 owns job-demand domain-row
  validation, idempotency, duplicate accounting, and audit events.
- `WORKFLOWS.md`: a data-quality behavior change requires a bounded package,
  tests, and Data Model / Version State self-review.

## Goal

For a job-demand dataset, retain one effective row for each non-empty
company-name and job-title pair. Prefer the record with the newest valid
`source_published_at`; if no candidate in a pair has a valid publication time,
retain the first source-order record.

## Scope

- B4 job-demand writer, fingerprint helper, and focused writer tests.
- B4 contract-freeze documentation and this task package.

## Out Of Scope

- Raw-object deletion, source-table mutation, cross-dataset deduplication,
  LLM extraction/routing changes, schema migrations, Console/API changes.
- Treating an empty company name as a common company; such records stay
  separate to avoid false merges.

## Forbidden Changes

- Do not change `record_fingerprint` or its dataset-scoped unique constraint:
  it remains the source-row traceability key.
- Do not discard raw input from `normalized_record` or weaken audit records.
- Do not call LiteLLM or external services from the cleaning step.

## Deliverables

- Deterministic company-and-role candidate selection before B4 persistence.
- `duplicate_company_job` quality accounting and audit summary coverage.
- Tests for newest-date selection, no-date first-row fallback, equal-date
  deterministic behavior, and blank-company non-merging.

## Acceptance

- Downstream `job_demand_record`, B5 extraction, chunking, and indexing see
  only the selected row for each effective company-and-role key.
- Original `record_count` remains the source-row count; `duplicate_count`
  reports discarded duplicates, and the quality summary distinguishes the
  new cleaning rule from exact source-row fingerprint duplicates.
