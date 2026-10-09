# Task Package: Job Collection C4 Raw Intake

## Goal

Persist crawler-engine parsed job values separately from immutable collection provenance, with an atomic page cursor checkpoint.

## Scope

- ORM and Alembic migration for `raw_jobs` and one-to-one `raw_job_provenance`.
- Provider-specific result handler behind the generic runtime extension point.
- Idempotent page acceptance, canonical hash validation, run count updates, and failure rollback tests.

## Out Of Scope

- Dataset snapshots, job demand identity, cleaning, extraction, and generic AI governance.
- Raw-record read APIs and Console displays of full job descriptions.

## Forbidden Changes

- No external call inside a database transaction.
- No cursor advance without durable page acceptance.
- No Pipeline B `normalized_record` or `normalized_asset_ref` dependency.

## Review Gates

- Data Model, Version State, Permission/Audit, and API Contract review of raw retention and run counts.

## Acceptance

- Same upstream record ID replay creates no duplicate raw job or provenance.
- A new upstream record ID retains a new raw version even with the same source job ID; the same record ID with changed raw payload fails.
- A failed page leaves cursor and counts unchanged. A successful page commits records and cursor together.
