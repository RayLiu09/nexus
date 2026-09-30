# Task Package: API Data Sync W5 Controls

## Goal

Support idempotent synchronous pause, resume, and cancel of sync runs. A successful downstream control response immediately updates the stable run status.

## Scope

- Internal administrator control APIs requiring `Idempotency-Key`.
- Synchronous adapter control calls outside database transactions, followed by an immediate status update.
- Idempotency keys tracked in existing audit history; key reuse for another action returns 409.
- Immediate local cancellation of a queued run without an external task.
- Safe control metadata, audit, and focused service/API tests.

## Out Of Scope

- Console controls (W6), result sink, Provider registration, and arbitrary manual status overrides.

## Forbidden Changes

- No external Provider or Token call inside a database transaction.
- No transitional `data_sync_run` status or `data_sync_run_event` table.
- No credential, raw response, or sensitive query value in audit records.

## Review Gates

- Data Model, API Contract, Permission And Audit, and Version State review before merge.

## Verification Evidence

- `nexus-api/tests/test_data_sync_run_controls_api.py` with plan/run API regression: 14 tests pass for synchronous lifecycle, queued cancellation, idempotency replay/conflict, 403/404/409/428, downstream failure, concurrent state changes, safe audit, and adapter calls outside database transactions.
- `nexus-app/tests/data_sync` plus `tests/test_worker_pool.py`: 33 tests pass with resumed-run claim and external paused-state handling.
- Alembic `20260930_0109` adds only the control audit enum value; no control request table or transitional run status.
