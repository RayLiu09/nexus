# Crawler Filter Status Semantics

## Source context

- `SPEC.md`: crawler intake retains traceable run and pipeline results.
- `WORKFLOWS.md`: P0 status and Console changes need focused verification and Frontend UX review.
- User decision: filtering a search result is normal behavior, not a failure.

## Goal

Keep filtered results visible without marking a Crawler run partially failed solely because of filtering.

## Scope

- Firecrawl and WebSearch run status/count summaries.
- Crawler run-history presentation and focused tests.
- Update prior task-package acceptance where it conflicts with this decision.

## Out of scope

- Admission rules, pipeline jobs, database schema, and bulk historical run migration.

## Forbidden changes

- Do not admit rejected content or weaken provider/ingest failure reporting.
- Do not change governance inputs, asset status rules, or audit contracts.

## Acceptance

- Filter-only runs are `succeeded` when some content is submitted and `no_results` when none is submitted.
- Filtered items contribute to `filtered_count`, not `failed_count` or `failures`.
- Idempotent duplicate submissions contribute to `duplicate_count`, not `failed_count` or `failures`.
- Provider, search, and ingest errors still produce `partial_failed` or `failed` as appropriate.
- The Console displays filtered and failed rows separately.
- The cited WebSearch run `908d6601-d832-4550-bc42-b76e7b9fa692` is corrected only after confirming its 35 accepted/submitted, 10 filtered, and zero true failures; the correction is recorded in its summary.

## Review gates

- Frontend UX: counts and detail labels agree with the final run status.
- API Contract / Version State: status values stay within the existing enum; only their crawler decision semantics change.
