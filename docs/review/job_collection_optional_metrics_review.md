# Crawler Optional Job Metrics Review (2026-11-20)

## Scope And Contract Review

- Shared receiving validation covers the five crawler-contracts 0.5.0 metrics;
  all are optional and accept explicit null. No upstream contract-package
  dependency is introduced because NEXUS uses local DTOs.
- Nullable main-table columns preserve real workplace, hiring count, publication
  wording, source date and explicit publication instant. Detailed address and
  collection region remain separate. Missing hiring count stays unknown and
  explicit zero is retained. Source dates/times are not inferred locally.
- The adapter returns original dictionaries after validation. Archival JSON,
  unknown fields, missing-vs-null distinctions and canonical hashing remain
  intact. Replay and raw-record conflicts use the existing identities.
- Invalid optional metrics produce bounded errors; no raw fields or secrets
  are added to logs/audit. Worker ownership, page checkpoints, permission rules,
  public responses and sync state semantics are unchanged.
- Initial implementation performed no live collection, database upgrade,
  deployment or historical backfill. The subsequent user-authorized database
  upgrade is recorded below.

## Verification

| Check | Evidence |
| --- | --- |
| Data-sync regression | From `nexus-app`: `.venv/bin/python -m pytest tests/data_sync -o addopts= -q` → **213 passed in 3.67s**. |
| Existing raw-job/public job APIs | From `nexus-api`: `.venv/bin/python -m pytest tests/test_raw_jobs_api.py tests/test_agent_public_business.py tests/test_market_job_analytics.py -o addopts= -q -o faulthandler_timeout=20` → **75 passed in 30.43s**. |
| Compatibility cases | Missing/null/partial metrics, explicit zero and positive count, source-date-only records, timezone-aware timestamps and future optional JSON fields. |
| Failure/replay cases | Negative/fractional/string/bool counts, invalid date/time types, naive timestamps, Unix-seconds strings, unchanged replay and changed-metric conflicts. Failed page retains prior cursor/counts and rolls back earlier writes in that page. |
| Migration | SQLite upgrade/downgrade preserves existing rows and nullable values, permits zero and rejects negative counts. PostgreSQL offline DDL verifies DATE, INTEGER, TIMESTAMP WITH TIME ZONE and absence of defaults/backfill. |
| Migration chain | `.venv/bin/python -m alembic heads` → sole head `20261120_0134`. |
| Static verification | `compileall` for receiving modules, ORM and migration; `git diff --check` passed. |

API tests initially stalled inside Starlette TestClient/AnyIO thread
communication in the restricted sandbox, before request handling. Diagnostic
tracebacks identified that wait; the same local SQLite-backed regression suite
completed outside the sandbox with approved escalation. Automated database tests
use SQLite and PostgreSQL offline DDL compilation; subsequent live PostgreSQL
migration verification is recorded below.
The page-rollback test enables explicit SQLite transactions to match PostgreSQL
savepoint semantics rather than sqlite3's legacy autocommit behavior.

## Data Model Gate And Deployment

Implementation/contract checks are prepared for human Data Model Gate review;
after receiving the implementation, test results and live migration verification,
the user explicitly instructed “提交并推送”. This authorizes committing and
pushing this bounded change on the current branch. No separate formal review
checklist completion is claimed.

Migration `20261120_0134` follows `20261118_0133`. Apply the migration before
restarting API services and data-sync workers that use the new ORM columns.
All five columns are nullable, without defaults or historical updates. A
nonnegative CHECK protects hiring counts. PostgreSQL ALTER/CHECK validation
uses table locks; schedule migration with the deployment's normal migration
window. Downgrade removes the five projections; original archived JSON remains.

## Authorized Development Database Upgrade

User follow-up instruction: “执行数据库升级”. Upgrade and read-only verification
completed on **2026-11-20 14:47:36 Asia/Shanghai** (06:47:36 UTC).

- Target: application's current `.env.dev` PostgreSQL database,
  `10.100.11.182:5432/nexus_dev`.
- Preflight revision: `20261118_0133`; none of the five new columns existed.
- Command from `nexus-app`:
  `PGCONNECT_TIMEOUT=5 PGOPTIONS='-c lock_timeout=10000 -c statement_timeout=60000' .venv/bin/python -m alembic upgrade 20261120_0134`.
- Alembic completed the single requested migration successfully with
  transactional PostgreSQL DDL. Verified revision: `20261120_0134`.
- All five columns have the expected PostgreSQL types, permit NULL and have no
  defaults. `ck_raw_jobs_hiring_count_nonnegative` exists, is validated and has
  definition `CHECK ((hiring_count >= 0))`.
- Before/after counts: `raw_jobs` **167,060 → 167,060**;
  `raw_job_provenance` **167,060 → 167,060**. Zero rows have any of the new metrics
  populated, consistent with no historical backfill.
- Restricted-sandbox connection was unavailable; preflight, upgrade and final
  verification ran with approved network escalation. Credentials were not
  printed or added to evidence.
- Service restart/deployment and live collection were not performed by this
  database-only follow-up.
