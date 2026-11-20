# Job Collection Raw Intake Contract

## Storage Boundary

The crawler-api response names the parsed job object `fields`. NEXUS stores its original business values in `raw_jobs`; a one-to-one `raw_job_provenance` row stores collection metadata and the complete upstream record. No `sync_batch` or observation table is created. Intake additionally performs simplified, deterministic title cleaning for queries. It does not invoke Pipeline B, generic governance, occupation normalization, deduplication, or dictionary processing.

`raw_jobs` has one row per upstream `recordId` version. Its columns map directly from the verified `fields` keys: `title`, `companyName`, `addressText`, `salaryText`, `experienceText`, `degreeText`, `hiringText`, `description`, `skillsText`, `jobTagsText`, `jobResponsibilitiesText`, `jobRequirementsText`, `qualificationsText`, `otherMattersText`, `companyIndustryText`, `companyScaleText`, and `companyFinancingText`. Only `title` is required. Missing and explicit null optional values are stored as SQL NULL; the original distinction and unknown keys remain in `raw_job_provenance.raw_record`.

### Optional Metrics (2026-11-20)

Crawler contracts 0.5.0 adds the following nullable typed projections. Both the
adapter and intake validate them; the full original record and its hash remain
unchanged.

| Upstream field | `raw_jobs` column | PostgreSQL type |
| --- | --- | --- |
| `fields.locationText` | `location_text` | text |
| `fields.hiringCount` | `hiring_count` | integer, CHECK >= 0 |
| `fields.publishTimeText` | `publish_time_text` | text |
| `fields.publishedDate` | `published_date` | date |
| `fields.publishedAt` | `published_at` | timestamptz |

`location_text` is actual workplace; `address_raw` remains detailed address and
`region` remains collection scope. No location is inferred from another field.
`hiring_count` remains NULL when absent, even if `hiring_raw` is present; zero
is a valid explicit value. Publication wording and source dates are retained
verbatim in original JSON. Typed dates come directly from the upstream response;
relative-time conversion is upstream-owned. An absent `publishedAt` stays NULL,
including when `publishedDate` exists. PostgreSQL preserves the instant in
`timestamptz`; original timezone/offset spelling remains in archived JSON.

Migration `20261120_0134` (after `20261118_0133`) adds nullable columns without
defaults or backfill and a nonnegative hiring-count check. Apply it before
restarting API services and data-sync workers with the new ORM. Existing records
remain NULL; replay does not repair projections or rewrite provenance. No public
response fields, filters, aggregates or Console columns are added in this slice.

### Provenance

`raw_job_provenance` owns provider/upstream record ID, source/job ID/URL, external Job/Task IDs, source page, query keyword/region, collection and receipt time, upstream `payloadHash`, and a canonical SHA-256 of the full record. `(provider_code, upstream_record_id)` is unique. `source_job_id` is nullable and not unique: a later upstream record ID for the same source job is a new raw version. The complete response is an immutable archival copy, while typed business columns support ordinary processing queries.

Raw rows count collected record versions, not distinct source jobs or deduplicated job demands. Later processing derives its own identity and snapshot boundaries without changing these original values. Raw content is never returned by the generic data-sync APIs or placed in logs/audit.

## Intake And Replay

New rows also save the query fields below in the same page transaction.

1. Fetch and validate an upstream page outside a database transaction.
2. Lock the `data_sync_run` row and verify worker ownership and fetched cursor.
3. In one short transaction, write each new `raw_jobs` / `raw_job_provenance` pair and advance the cursor and existing run counters. If a record ID already exists with the same canonical hash, count a replay; a changed hash is a contract failure.
4. A failed page rolls back its rows, counters, and cursor. A terminal upstream Job is required before a null cursor can complete the run, because a running Job can return an empty/null page.

The existing `data_sync_run` is an execution checkpoint for the generic sync framework. NEXUS does not add a second collection state machine or batch/observation lifecycle for raw jobs.

## Simplified Query Fields (2026-11-17)

- Nullable `raw_jobs.title_normalized` is a local `simple-v2` cleaned copy of
  `title_raw`: NFKC, whitespace/invisible-character cleanup, explicit recruitment
  advertising markers, recognized trailing job IDs and whitespace-separated
  salary decorations. Version 2 adds sample-driven benefit, commute, schedule,
  explicit recruitment-acceptance and remote-collaboration cleanup. Mixed
  brackets retain non-noise content, such as `(合同制+六险二金)` → `(合同制)`.
  Preserve rank, specialty, semantic parentheses, platform,
  employment type, geography and compound jobs. Empty cleaning falls back to
  basic normalized text. No LLM, synonym inference or standard-job assignment.
- Nullable `raw_jobs.region` copies upstream `record.region` verbatim (string,
  up to 80 characters), just as provenance.query_region does. The main-table
  copy supports queries; it is collection scope, not actual work location.
  Missing region remains NULL even when address_raw contains a location.
- Original fields, original record/hash and upstream-record uniqueness remain
  unchanged. Replay does not refresh or change query fields.
- Public `/open/v1/market-jobs` and `/aggregate`, internal
  `/internal/v1/raw-jobs` and `/export` accept optional `region`: escaped,
  case-insensitive literal substring matching against `raw_jobs.region` before
  pagination/aggregation/export. NULL regions do not match. It no longer matches
  address_raw, does not expand provinces into cities and combines other filters
  with AND. Existing job_title responses retain title_raw; responses add
  title_normalized and region. Title searches match raw and cleaned text.
- Internal Excel export appends cleaned title and collection region, retaining
  existing column positions. No new UI workflow is introduced.
- Migration `20261117_0132` adds nullable columns only. Apply it before service
  restart. Run `nexus-app/scripts/backfill_raw_job_title_region.py` for historical
  data (dry-run default, `--apply` to persist, `--batch-size 500`, optional
  `--after-id`). It fills missing values from title_raw/provenance.query_region,
  commits each keyset batch with repair audits, preserves raw timestamps and
  provenance, and can be rerun without rewriting already populated fields.
  Missing provenance never triggers address-based region inference.
- `--reclean-titles` explicitly recomputes populated titles from title_raw with
  current rules; without it, only missing fields are filled. Dry-run remains the
  default, only changed titles are written/audited and region stays unchanged
  when already populated. Salary-first full-detail blocks are detected and kept
  as basic text; a missing true job title is never inferred from other keywords.
