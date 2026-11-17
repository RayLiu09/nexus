# Task Package: Raw Job Title Cleaning And Collection Region

Date: 2026-11-17. Single agent, sequential implementation.

## Source And Goal

- User approves simplified title cleaning independent of future job normalization.
- User requires `raw_jobs.region` to retain the collection-time region; keep
  `address_raw` and support region queries in public and internal APIs.
- Follow ARCHITECT.md raw-intake boundary, SPEC.md API sync contract,
  Prototype v2.2 existing market job list, and WORKFLOWS.md review gates.

## Frozen Scope

- Add nullable `title_normalized` and `region` columns with an additive migration.
- Local deterministic title cleaning preserves rank, specialty and employment
  type; remove only explicit decorations/advertising and recognized job IDs.
- Copy upstream `record.region` without administrative/geographic inference.
- Keep raw fields, provenance hashes, record identity and page atomicity intact.
- Public list/aggregate and internal list/export filter the main-table region
  using escaped case-insensitive literal substring matching before pagination.
- Return both new fields; include them in internal Excel export, preserving
  existing column order by appending new columns.
- Search titles across raw and cleaned values; retain raw job_title responses.
- Supply bounded keyset backfill, dry-run by default, only filling missing
  columns from title_raw and provenance.query_region; audit persisted repairs.
- Update contracts, generated tools, tests and review evidence.

## Excluded And Forbidden

- No province/city parsing, geographic dictionaries, AI calls, occupation
  classification, deduplication or coupling to future job normalization.
- No Pipeline B/governance reactivation or new status machine.
- No frontend workflow changes, service restart, deployment, production data
  writes, merge or commit as part of this implementation.
- No change to source payloads, hashes, collection or receipt timestamps.

## Acceptance And Review

- Cleaning preserves semantic parentheses, seniority and technical terms;
  deterministic repeated cleaning and conservative empty-result fallback.
- Intake replay/conflict/rollback tests continue to pass with new fields.
- Region/address disagreement proves filters use collection region only;
  list totals, pagination, aggregation and export share the region scope.
- Literal `%`/`_`, absent regions and combined filters are covered.
- Backfill dry-run, repeat execution, missing provenance and audit verified.
- Migration upgrade/downgrade and generated-tool drift checks pass.
- Data Model and API Contract review evidence prepared; Permission/Audit
  evidence covers existing public authentication and repair attribution.
- Human approval before merge remains required by WORKFLOWS.md; implementation
  evidence does not assert that approval.

## Delivered

- ORM, nullable-column migration, local title cleaner, collection-region intake,
  API response/search/filter and export changes implemented.
- Historical missing-field repair supports dry-run, batched commit and audit.
- Final verification: 78 core/migration/repair tests and 44 API/tool-contract
  tests passed (122 total); earlier implementation-only counts were 24 and 44.
- 55 public tools regenerated and artifact drift check passed.
- [Review evidence](../review/wk_raw_jobs_title_region_review.md) documents
  Data Model/API Contract/Permission And Audit checks and rollout instructions.
- Initial implementation performed no live schema/data changes, service restarts,
  deployment or merge.

## Authorized Local Database Follow-up

- User explicitly requests updating the local database after implementation.
- Inspect the local connection and migration revision without exposing secrets;
  apply migration `20261117_0132`, preview and apply historical missing-field
  repair, and verify schema, coverage, audits and preserved original data.
- This extends scope to local database writes only. No production deployment,
  service restart or merge is included.
- Development DB contains 142,272 jobs at revision `20261030_0129`. Reviewed
  prerequisite migrations `0130` (audited rules version, no historical rewrite)
  and `0131` (tag lookup index) precede the additive `0132` migration.
- Repair loads only needed title/region fields and batches row updates plus
  per-row audit inserts, avoiding a network round trip per historical job.
- User reports benefits/commute/remote-collaboration/intern-acceptance text left
  in titles and requests rules based on existing job samples. Inspect aggregate
  title fragments, expand explicit-noise rules with semantic preservation tests,
  preview and audit re-cleaning of existing development titles from title_raw.
- `simple-v2` preview scans all 142,272 titles: 22,251 changes, zero empty
  results and zero non-idempotent results. 78 focused core/migration/repair tests
  pass. 8,006 detected salary-first detail blocks are preserved, not guessed.
- Applied local development migrations through `20261117_0132` and filled both
  new fields on 142,272 jobs. Subsequent simple-v2 re-clean updated 22,251 titles
  and no regions. Final full-title recomputation has zero mismatches; original
  raw-field/provenance checksums remain identical. Audit counts match both runs.

## Commit And Push Authorization

- User explicitly requests committing and pushing the completed changes.
- Commit only this task's code, migration, tests, contracts, generated tools,
  task package and review evidence. Preserve unrelated workspace changes.
