# Task Package: Retire Job Demand Pipeline B And AI Governance

## Source Context

- `AGENTS.md`: pipeline routing is persisted at job creation; governance rules and Prompt mutations are auditable.
- `docs/task-packages/wk_job_collection_c4_raw_intake_task_package.md`: crawler job postings persist as `raw_jobs` and provenance, without Pipeline B normalized records.
- `WORKFLOWS.md`: AI Governance, Rule Engine, Version State, and Data Model review gates apply.

## Goal

Keep new crawler job postings in raw job intake and retire the legacy job-demand Pipeline B and AI-governance configuration.

## Scope

- Stop job-demand profile detection, domain writing, extraction, Markdown rendering, and graph construction in the active worker path.
- Remove job-demand governance classification and AI analysis rule seeds and retire active database configuration with an Alembic migration.
- Preserve historical business rows and read APIs.

## Out Of Scope

- Deleting historical job-demand datasets, records, graphs, or read APIs.
- Redesigning the crawler-engine raw intake or job dictionary pipeline.

## Forbidden Changes

- Do not route crawler job postings through normalized records.
- Do not remove unrelated Pipeline B profiles or governance classifications.
- Do not alter archived governance rule versions.

## Acceptance

- Crawler JSON no longer gets a Pipeline B job payload by default.
- No active job-demand writer, extraction, renderer, or graph stage runs.
- Fresh governance rules and AI analysis seeds do not include job-demand classification or scenarios.
- Migration archives the prior active governance rules and creates a replacement without `job_demand`; historical data remains readable.
- Routing tests, JSON validation, Python compilation, and `git diff --check` pass.
