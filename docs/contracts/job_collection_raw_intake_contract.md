# Job Collection Raw Intake Contract

## Storage Boundary

The crawler-api response names the parsed job object `fields`. NEXUS stores its original business values in `raw_jobs`; a one-to-one `raw_job_provenance` row stores collection metadata and the complete upstream record. No `sync_batch` or observation table is created. This intake does not invoke Pipeline B, generic governance, cleaning, deduplication, or dictionary processing.

`raw_jobs` has one row per upstream `recordId` version. Its columns map directly from the verified `fields` keys: `title`, `companyName`, `addressText`, `salaryText`, `experienceText`, `degreeText`, `hiringText`, `description`, `skillsText`, `jobTagsText`, `jobResponsibilitiesText`, `jobRequirementsText`, `qualificationsText`, `otherMattersText`, `companyIndustryText`, `companyScaleText`, and `companyFinancingText`. Only `title` is required. Missing and explicit null optional values are stored as SQL NULL; the original distinction and unknown keys remain in `raw_job_provenance.raw_record`.

`raw_job_provenance` owns provider/upstream record ID, source/job ID/URL, external Job/Task IDs, source page, query keyword/region, collection and receipt time, upstream `payloadHash`, and a canonical SHA-256 of the full record. `(provider_code, upstream_record_id)` is unique. `source_job_id` is nullable and not unique: a later upstream record ID for the same source job is a new raw version. The complete response is an immutable archival copy, while typed business columns support ordinary processing queries.

Raw rows count collected record versions, not distinct source jobs or deduplicated job demands. Later processing derives its own identity and snapshot boundaries without changing these original values. Raw content is never returned by the generic data-sync APIs or placed in logs/audit.

## Intake And Replay

1. Fetch and validate an upstream page outside a database transaction.
2. Lock the `data_sync_run` row and verify worker ownership and fetched cursor.
3. In one short transaction, write each new `raw_jobs` / `raw_job_provenance` pair and advance the cursor and existing run counters. If a record ID already exists with the same canonical hash, count a replay; a changed hash is a contract failure.
4. A failed page rolls back its rows, counters, and cursor. A terminal upstream Job is required before a null cursor can complete the run, because a running Job can return an empty/null page.

The existing `data_sync_run` is an execution checkpoint for the generic sync framework. NEXUS does not add a second collection state machine or batch/observation lifecycle for raw jobs.
