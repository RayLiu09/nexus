# Job Collection Raw Intake Verification

Date: 2026-10-08. Query: `数据化运营助理`, `杭州市`, 10 source pages. Provider: `crawler_engine` (`zhaopin`). The private Provider Catalog is gitignored and mode 600; this report contains no tenant key, access token, source URL, company name, or job description.

## Migration And Run

- Development PostgreSQL was at Alembic `20260930_0109` with none of the previous draft raw-intake tables present. Migration `20261008_0110` created `raw_jobs` and `raw_job_provenance`.
- One monthly plan and one manual run were created through the existing data-sync services. The run ID is `5f2062a6-8010-4472-802d-707df95a586e`.
- Upstream transitioned `queued -> running -> succeeded`. The NEXUS run finished `succeeded` with `processed_count=56`, `success_count=56`, `skipped_count=0`, and no failure code.
- The run's external Job has 56 matching `raw_jobs` and 56 matching `raw_job_provenance` rows. All 56 upstream record IDs are distinct, source pages cover 1 through 10, and there are no raw jobs without provenance.
- Replaying one stored real record through the PostgreSQL receiver returned `accepted=0`, `duplicate=1`; the raw job count remained 56.
- Original nullable content was retained: 52/56 descriptions, 29/56 responsibility fields, and 6/56 requirement fields were nonempty. These counts are source facts, not intake failures.

## Verification

- `nexus-app`: `49` data-sync tests passed using SQLite.
- `nexus-api`: control and Catalog API tests passed (`6` tests) against the available development database.
- Real PostgreSQL migration and end-to-end adapter intake passed.

The 56 rows count collected raw record versions. They are not deduplicated job-demand entities. Future cleaning and statistics must define their own population and identity rules.
