# Task Package: API Data Sync W0/W1 Catalog

## Source Context

- `docs/api_data_sync_framework_implementation_plan.md` v1.6: file-backed Provider Catalog, adapter-owned query schema and Token protocol, immutable sync plans, seven run states, deferred result sink.
- `ARCHITECT.md`, `SPEC.md`, `WORKFLOWS.md`: PostgreSQL polling, internal Console control APIs, audit, and review gates.

## Goal

Freeze the data-sync contract and deliver the first executable slice: a validated, file-backed Provider Catalog with a Mock adapter and read-only internal API.

## Scope

- Update `ARCHITECT.md`, `SPEC.md`, and `readme.md` for the new API Push boundary.
- Add a JSON Provider Catalog, loader, query adapter boundary, and Mock adapter in `nexus-app`.
- Freeze state, API, idempotency, migration draft, and Review Gate details in `docs/contracts/api_data_sync_contract.md`.
- Add `GET /internal/v1/data-sync/providers` in `nexus-api`.
- Add focused loader, validation, and API tests.

## Out Of Scope

- No `data_sync_config` or `data_sync_run` migration, scheduling, Worker, Token exchange, external provider, result sink, or Console page in this slice.
- No changes to existing ingest or crawler pipelines.

## Forbidden Changes

- Do not persist Provider Catalog in a database or hardcode its entries.
- Do not place query schema, Token API URL, or tenantKey plaintext in Catalog JSON.
- Do not let requests select arbitrary adapter code.
- Do not introduce RabbitMQ, Celery, Redis, or a new gateway.

## Deliverables And Acceptance

- Startup/config loader rejects malformed, duplicate, or incompatible Provider entries.
- Mock Provider appears through an authenticated read-only internal API, including adapter query schema and credential availability, without exposing the Secret reference or value.
- Focused tests pass; root docs and implementation plan agree on ownership.

## Follow-On Packages

- W1 plan persistence/API: immutable `data_sync_config`, `active`/`paused`/`deleted`, audited controls, migration.
- W2 credentials/Token runtime.
- W3-W5 run persistence, scheduler/Worker, and run controls.
- W6-W8 Console, audit view, end-to-end testing and Review Gates.

## Review Gates

- Architecture Review and API Contract Gate for this slice.
- Data Model, Permission And Audit, Version State, and Frontend UX Gates as their later slices are implemented.
