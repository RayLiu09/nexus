# Task Package: Major Distribution Province Name Normalization

## Source Context

- `AGENTS.md`: Pipeline B normalized records are the only valid source for
  domain read models; retrieval changes need focused tests and verification.
- `ARCHITECT.md`: Pipeline B major-distribution records are normalized into
  `major_distribution_dataset` / `major_distribution_record` read models.
- `WORKFLOWS.md`: structured retrieval behavior needs test evidence; no schema
  or external API response-contract expansion is required for this fix.

## Goal

Normalize Chinese province-level administrative division names consistently so
queries using common short forms, such as `新疆`, retrieve records stored under
their canonical names, such as `新疆维吾尔自治区`.

## Scope

- Add a reusable province-level name normalizer in `nexus-app`.
- Apply it to Pipeline B major-distribution writer input and query filters in
  Query Router and `/v1` major-distribution APIs.
- Add an idempotent, dry-run-by-default backfill script for existing
  `major_distribution_record.province_name` values.
- Add focused unit/API/script tests and execute the approved backfill against
  the configured development database.

## Out Of Scope

- New database columns, migrations, or response-schema changes.
- Aggregating separate records such as `新疆维吾尔自治区` and
  `新疆生产建设兵团`.
- Normalizing city, district, foreign-region, or free-text location fields.

## Forbidden Changes

- Do not alter raw or normalized-record source payloads.
- Do not merge distinct administrative entities or rewrite their counts.
- Do not use unconstrained fuzzy SQL matching as the canonical query behavior.
- Do not introduce new infrastructure or external dependencies.

## Deliverables

- Canonicalization helper with known aliases and pass-through handling for
  unknown values.
- Write and read-path integration for major-distribution records.
- Idempotent backfill script with `--apply`, dry-run output, and scoped IDs.
- Tests for aliases, new writes, retrieval/API queries, and backfill outcomes.

## Acceptance

- `province_name=新疆` returns the `新疆维吾尔自治区` major-distribution
  record when it exists.
- `新疆生产建设兵团` remains an independent result and is never combined.
- New `新疆` writer input persists as `新疆维吾尔自治区`.
- Dry-run makes no changes; apply changes only recognized legacy aliases and
  can be rerun without further writes.
