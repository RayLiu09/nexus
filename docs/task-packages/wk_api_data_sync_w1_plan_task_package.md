# Task Package: API Data Sync W1 Plans

## Source Context

- `docs/api_data_sync_framework_implementation_plan.md` v1.6 and `docs/contracts/api_data_sync_contract.md` freeze immutable plans and the control API.
- `WORKFLOWS.md` requires Data Model, API Contract, Permission And Audit gates.

## Goal

Persist independent sync plans and expose authenticated create/list/read/pause/resume/soft-delete APIs.

## Scope

- `data_sync_config` ORM, Alembic migration, schemas, service, internal API and focused tests.
- Idempotent creation, adapter query validation, five frequency choices, state control audit.

## Out Of Scope

- No sync-run table or scheduling Worker. A deletion conflict with a nonterminal run becomes enforceable when W3 adds `data_sync_run`; no run can exist through this slice.
- No Token request, result storage, Console page, or real Provider.

## Forbidden Changes

- Do not edit plan name/Provider/frequency/query after creation.
- Do not persist Provider definitions, Secret references, or tenantKey in plan rows.
- Do not change crawler plans or ingest jobs.

## Acceptance

- Same actor and idempotency key return the same plan for identical input, 409 for different input.
- Invalid Provider, disabled Provider, or invalid adapter query is rejected.
- Paused/deleted plans cannot be edited; pause/resume/delete are audited, repeated actions idempotent.
- Deleted plans remain readable by ID for history and are excluded from normal list.

## Review Gates

- Data Model Gate, API Contract Gate, Permission And Audit Gate.

## Verification Evidence

- `nexus-api/tests/test_data_sync_plans_api.py`: create/idempotency/conflict, plan controls, query rejection, and audit events.
- `nexus-app/tests/data_sync/test_plans.py`: month-end schedule calculation.
- Human Review Gates completed as confirmed by the project owner on 2026-09-29; see `docs/review/api_data_sync_w0_w1_evidence.md`.
