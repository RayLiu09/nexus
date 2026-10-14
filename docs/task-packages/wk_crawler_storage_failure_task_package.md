# Crawler Storage Failure State

## Source context

- `docs/task-packages/wk_crawler_websearch_custom_task_package.md`: accepted WebSearch results are stored as raw objects before Pipeline A jobs are submitted.
- `WORKFLOWS.md`: crawler run status and audit changes require focused API and permission/audit review.
- Incident: WebSearch runs `29155087-3259-4bc1-891a-6352e5373f0c` and `4746b467-cc06-4292-8250-bd033c098b60` created open batches without raw objects while MinIO was unavailable.

## Goal

Persist a terminal, auditable WebSearch run outcome when object storage rejects an accepted result.

## Scope

- Classify object storage write errors with a bounded reason in the run summary.
- Stop further appends after a storage outage and preserve counts for already submitted results.
- Mark an empty batch failed when no jobs were created.
- Add focused failure-path tests.

## Out of scope

- Replaying or editing historical runs and batches.
- Changing provider search, admission rules, raw package format, or pipeline jobs.
- Automatic retry of the whole crawler plan.

## Forbidden changes

- Do not store upstream result bodies, credentials, or raw exception messages in the run summary or audit.
- Do not change Pipeline A routing or asset/version status rules.

## Acceptance

- A storage write failure returns a `failed` run with one bounded failure reason and no raw object or Job.
- A prior successful append remains visible and the run is `partial_failed` if storage fails later.
- The run and empty batch no longer remain `running` and `open` after a caught storage failure.
- A completion audit event links to the run and trace ID.

## Review gates

- API Contract Gate: existing response schema and status enum remain unchanged.
- Permission And Audit Gate: failure summaries contain no result body or secrets, and the completion event is traceable.
