# Task Package: Crawler Optional Job Metrics (2026-11-20)

## Source Context And Goal

- Upstream crawler contracts 0.5.0 adds five optional `fields` properties to
  `GET /v1/collection-jobs/{jobId}/records`.
- Follow `ARCHITECT.md` raw-job intake boundary, `SPEC.md` collection semantics,
  and `WORKFLOWS.md` task-package and Data Model Gate requirements.
- Receive, validate and persist the metrics without changing original records,
  hashes, page checkpoints or replay identities.

## Scope

- Adapter and intake share validation for optional `locationText`, `hiringCount`,
  `publishTimeText`, `publishedDate`, and `publishedAt`.
- Add nullable `raw_jobs` columns `location_text`, `hiring_count`,
  `publish_time_text`, `published_date`, and `published_at` with an additive
  Alembic migration. Existing rows remain NULL.
- Retain unknown optional extensions and missing-vs-null distinctions in the
  immutable original JSON. Keep workplace, detailed address and query region
  separate; preserve upstream dates without deriving dates or times locally.
- Add adapter, intake, rollback/replay and migration regression evidence; update
  provider/storage contracts and root documentation.

## Out Of Scope And Forbidden Changes

- No UI or public API expansion, new filters/statistics, historical backfill,
  live collection or service deployment.
- Follow-up user authorization: execute the database upgrade to `20261120_0134`
  on the configured application database after checking its current revision,
  then verify columns, constraints and migration state. No service restart.
- No new crawler-contracts dependency: NEXUS owns its receiving DTOs.
- No Pipeline B, generic governance, AI extraction or changes to sync states,
  idempotency, permissions, audit payloads, IAM or gateway boundaries.

## Acceptance And Review

- Missing/null metrics persist as NULL; explicit zero is retained. Reject
  negative/fractional/coerced counts, malformed dates and naive timestamps.
- Preserve timezone-aware timestamps and full original JSON, including future
  extensions. Replay is idempotent and conflicts/invalid pages keep checkpoints.
- Migration upgrade/downgrade retains old rows; PostgreSQL DDL uses DATE and
  TIMESTAMP WITH TIME ZONE.
- Run `.venv/bin/python -m pytest tests/data_sync -o addopts= -q` from `nexus-app`.
- Data Model Gate: prepare migration/verification evidence for human review
  before merge, as required by `WORKFLOWS.md`. The user subsequently authorized
  commit/push after receiving implementation and migration evidence.
  Single-agent implementation.

## Verification Evidence

- Data-sync regression: **213 passed**; API raw-job/public market-job regression:
  **75 passed**.
- Migration upgrade/downgrade, PostgreSQL DDL and single Alembic head verified.
- Details and human review status:
  `docs/review/job_collection_optional_metrics_review.md`.
- User-authorized development DB upgrade completed on 2026-11-20:
  `10.100.11.182:5432/nexus_dev`, `20261118_0133` → `20261120_0134`.
  Live column types/nullability/defaults and validated nonnegative constraint
  verified. Raw-job/provenance counts remain 167,060 each; no backfill.
