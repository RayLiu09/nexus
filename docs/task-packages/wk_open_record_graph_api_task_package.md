# Task Package: Open Record Retrieval And Capability Graph APIs

## Goal

Expose cross-dataset record retrieval, major-distribution aggregation, and
read-only capability graphs through `/open/v1` for authenticated API callers.

## Scope

- Cross-dataset job-demand records filtered by job, company, city, education,
  industry, and experience text.
- Major-distribution aggregate query filtered by year, province, major name,
  and major code.
- Public read adapters for existing job-demand, ability-analysis, and
  teaching-standard capability graph staging projections.
- API Caller audit events, bounded pagination/response caps, focused tests,
  and API contract documentation.

## Decisions

- Structured record domains are queryable across datasets. `dataset_id` is a
  trace/narrowing field, never a required route hierarchy for Open API search.
- Record-domain Open API reads do not require an `available` asset version.
- `/internal/v1` graph preview APIs remain unchanged; public graph APIs never
  trigger a build, rebuild, promotion, or graph state transition.
- Public graph responses retain source build/ref identifiers but omit internal
  control-plane fields and are bounded by a fixed node/edge cap.

## Out Of Scope

- New graph storage, graph rebuild API, write/mutation API, LLM graph creation,
  experience-year backfill, and per-route restricted API key scopes.

## Acceptance

- API caller can filter job-demand records across datasets on every requested
  dimension.
- API caller can obtain grouped major-distribution totals without client-side
  pagination aggregation.
- API caller can read existing graph projections by job title or major identity,
  with source traceability and no internal endpoint exposure.
- Focused Open API and audit tests pass.

## Frozen Public Routes

- `GET /open/v1/record-assets/job-demand-records`: cross-dataset filters for
  `job_title`, `company_name`, `city`, `education`, `industry`, and
  `experience`.
- `GET /open/v1/record-assets/major-distribution-records`: cross-dataset
  filters for `year`, `province_name`, `major_name`, and `major_code`.
- `GET /open/v1/record-assets/major-distribution-records/aggregate`: the same
  filters with repeated `group_by` dimensions from `year`, `province_name`,
  `major_name`, and `major_code`; returns `distribution_total` and
  `record_count` per group.
- `GET /open/v1/record-assets/graphs/job-capability?job_title=`.
- `GET /open/v1/record-assets/graphs/occupational-capability?major_name|major_code=`.
- `GET /open/v1/record-assets/graphs/teaching-standard-knowledge?major_name|major_code=`.

The old public dataset-scoped `/{dataset_id}/records` routes are deliberately
not registered. Dataset-scoped reads and graph-control APIs remain under
`/internal/v1` for Console and operational workflows.
