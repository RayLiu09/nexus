# Task Package: API Data Sync W3 Runs

## Source Context

- `docs/api_data_sync_framework_implementation_plan.md` W3 and `docs/contracts/api_data_sync_contract.md` freeze the seven run states, immutable query snapshot, and internal API.
- `WORKFLOWS.md` requires Data Model, API Contract, Permission And Audit, and Version State review.

## Goal

Persist provider-independent sync runs and allow platform administrators to create and inspect queued runs from active plans.

## Scope

- `data_sync_run` ORM and Alembic migration with one nonterminal run per plan.
- Manual and scheduled queued-run creation with caller/slot idempotency, immutable query/hash and adapter-version snapshot, and audit.
- Internal run list/detail API with bounded pagination and filters.
- Plan deletion conflict while a nonterminal run exists.
- Focused model/service/API tests and contract updates.

## Out Of Scope

- No scheduler, Worker claim, external submit/poll/page fetch, retry, run controls, result sink, or Console page; those are W4-W6.
- No new event table or data-source coupling.

## Forbidden Changes

- Do not persist tenantKey, access token, or raw provider responses in run fields, API, logs, or audit.
- Do not introduce a `created` or control-transition run status.
- Do not cascade-delete runs when a plan is soft-deleted.

## Acceptance

- Run creation from an active plan returns `queued`; paused/deleted plans return 409.
- Same plan/actor/key or plan/schedule-slot returns the same run while the plan is active; an existing nonterminal run blocks a distinct request with 409.
- Query snapshot/hash and adapter version are fixed at creation; later plan/Catalog changes do not mutate them.
- Plan deletion returns 409 while a run is queued/running/paused; terminal runs do not block deletion.
- Run list filters and pagination return an accurate total; all creation is audited.

## Review Gates

- Data Model, API Contract, Permission And Audit, Version State Gates require human review before merge.

## Verification Evidence

- `nexus-app/tests/data_sync/test_runs.py`: scheduled slot replay, nonterminal exclusion, audit, and inactive-plan rejection.
- `nexus-api/tests/test_data_sync_runs_api.py`: manual replay, database partial unique index, snapshot isolation, deletion conflict, pagination, and invalid time filters.
- Alembic head: `20260930_0107`. External execution and result handling are W4 and later.
- Review Gate status: evidence prepared; human approval pending before merge.
