# Task Package: API Data Sync W4 Runtime

## Goal

Run queued `data_sync_run` records through a provider adapter with PostgreSQL-safe scheduling, leases, heartbeats, bounded retries, cursor persistence, and terminal settlement.

## Scope

- Provider runtime protocol and Mock Provider submit/status/page behavior.
- Scheduler tick that creates one scheduled run for each due active plan and advances `next_run_at` atomically.
- Worker claim, lease heartbeat, expired-lease recovery, and one-run execution loop.
- Submit/poll/fetch-page execution with cursor and safe counters persisted after each page.
- Error classification for 401 refresh, 408/429/5xx retry, 409 recovery, and 422 terminal failure.
- Focused unit tests and W4 implementation/contract updates.

## Out Of Scope

- Pause/resume/cancel API controls (W5).
- Persisting fetched business records or result sinks.
- RabbitMQ, Celery, Redis, or a productized operations center.

## Forbidden Changes

- Never persist tenant keys, access tokens, raw provider responses, or business records.
- Do not add transitional run statuses or a `data_sync_run_event` table.
- Do not infer pipeline type or couple runs to `data_source`.

## Review Gates

- Data Model, API Contract, Permission And Audit, and Version State gates require human review before merge.

## Verification Evidence

- `nexus-app/tests/data_sync/test_runtime.py`: scheduler due-plan creation and paused-plan exclusion, claim/lease recovery, Mock Provider paging, cursor resume, 401/409 recovery, 503 retry, 422 failure, and state-transition audit.
- `nexus-app/tests/data_sync` plus `tests/test_worker_pool.py`: 32 tests pass after W4 runtime additions.
- Provider Catalog and all Token/submit/status/page calls execute outside database transactions; each persisted progress update uses a short transaction and checks lease ownership.
- W4 runtime is opt-in in `Settings.data_sync_runtime_enabled`; existing WorkerPool remains unchanged when disabled.
