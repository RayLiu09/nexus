# Task Package: Finance Commerce Job Title Metadata

## Source Context

- `WORKFLOWS.md`: bounded task package and Data Model/API Contract Review Gates.
- `docs/task-packages/wk_job_collection_c6_console_catalog_task_package.md`: database-backed title catalog and stable category relationship.
- User-provided 29-row finance-commerce job title, type, and crawl-keyword table.

## Goal

Persist the 29 requested titles under `财经商贸类` with their job type and crawl keywords, without duplicating existing title rows.

## Scope

- Add nullable `job_category` and `crawl_keywords` fields to `job_collection_title`.
- Add an idempotent data migration for the 29 supplied records and expose the fields in the existing internal catalog response.
- Apply the migration to the local database and verify exact values and catalog visibility.

## Out Of Scope

- Automatic expansion of crawler queries from the stored keyword text.
- Editing existing sync plans or removing the 76-row original catalog seed.

## Forbidden Changes

- Keep category and title IDs stable for existing records.
- Do not add an external business API or modify crawler-api contracts.

## Acceptance

- All 29 names have the supplied type and keyword text under `财经商贸类`.
- Existing same-name titles remain single logical catalog choices.
- Migration is repeatable, API catalog exposes the two new fields, and focused tests pass.
