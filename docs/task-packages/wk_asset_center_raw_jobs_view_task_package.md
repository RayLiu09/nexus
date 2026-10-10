# Task Package: Asset Center Raw Job Demand View

## Goal

Expose crawler-intake job postings in the Asset Center as a paginated list
backed directly by `raw_jobs`.

## Scope

- Add a read-only Console API over `raw_jobs` and its provenance URL.
- Replace the placeholder `/asset-center/market/job-demands` view with a list
  showing job title, responsibility requirements, experience, education, salary,
  industry, company, company size, and address.
- Count the Asset Center resource from `raw_jobs`.

## Out Of Scope

- Reads or writes to the retired Pipeline B `job_demand_*` tables.
- Job normalization, governance, editing, or deletion.

## Acceptance

- The page is paginated and supports keyword and industry filtering.
- Every displayed field is mapped from `raw_jobs`; no Pipeline B projection is
  queried.
- Focused API, Console typecheck, lint, and component verification pass.
