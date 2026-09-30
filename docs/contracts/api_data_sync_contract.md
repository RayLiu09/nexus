# API Data Sync Contract (W0)

Status: implementation contract for W1-W8. Source: `docs/api_data_sync_framework_implementation_plan.md` v1.7.

## Ownership And Boundaries

- The Provider Catalog is deployment-owned. It declares Provider metadata, an API server URL containing only scheme/host/optional port, `tenant_id`, `tenant_name`, `tenant_key`, and adapter reference. The committed Mock Catalog contains a fake key; real keys belong only in a private deployment Catalog selected through `DATA_SYNC_PROVIDER_CATALOG_PATH`. The Catalog is not a database table or a user-editable resource.
- The adapter owns query schema, Token API endpoint and protocol, submit/status/page/control protocols, and external state mapping. The Catalog may reference only trusted deployed adapters.
- `data_sync_config` is an immutable user-created sync plan. Name, Provider, frequency, and query parameters cannot be edited. `active`, `paused`, and `deleted` are plan states. Pause blocks future scheduled and manual runs; it does not control an existing run. Delete is soft and returns 409 while a nonterminal run exists.
- `data_sync_run` is one execution of a plan. It stores an immutable query snapshot and adapter version. It does not store fetched business records in this phase. A result sink is reserved for a later contract.
- This flow is separate from `data_source`, the existing ingest Job pipeline, and crawler plans. It uses PostgreSQL polling and the existing audit log; no MQ, Celery, Redis, or new run-event table.

## States

Plan: `active -> paused -> active`; `active|paused -> deleted`. `deleted` is terminal. Repeated pause/resume/delete requests are idempotent if the target state has already been reached.

Run: `queued -> running -> paused -> running`; `queued|running|paused -> cancelled`; `running -> succeeded|partially_succeeded|failed`. Terminal states cannot be controlled. A control request does not introduce a transition state; the next external status poll confirms the stable state.

## Internal API Draft

All paths below are Console control-plane APIs under the existing authenticated `/internal/v1` router and require the platform/data administrator role. Every mutation requires `Idempotency-Key` and an audit record with `trace_id`. Error bodies use the existing API envelope.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/internal/v1/data-sync/providers` | Read-only Catalog view and adapter query schema; implemented in W0/W1 slice. |
| GET | `/internal/v1/data-sync/plans` | List plans; deleted plans are excluded unless explicitly requested. |
| POST | `/internal/v1/data-sync/plans` | Create immutable plan with `name`, `provider_code`, `frequency`, and `query_config`; returns 201. |
| GET | `/internal/v1/data-sync/plans/{plan_id}` | Read plan and current schedule state. |
| POST | `/internal/v1/data-sync/plans/{plan_id}/pause` | Stop future run creation. |
| POST | `/internal/v1/data-sync/plans/{plan_id}/resume` | Resume scheduling. |
| DELETE | `/internal/v1/data-sync/plans/{plan_id}` | Soft-delete plan; 409 if any run is nonterminal. |
| POST | `/internal/v1/data-sync/plans/{plan_id}/runs` | Manually create a queued run from an active plan; returns 201. |
| GET | `/internal/v1/data-sync/runs` | Filter by Provider, plan, status, and time; paginated. |
| GET | `/internal/v1/data-sync/runs/{run_id}` | Read run status, external task, counts, cursor, and safe summary. |
| POST | `/internal/v1/data-sync/runs/{run_id}/pause` | Ask adapter to pause an active external task. |
| POST | `/internal/v1/data-sync/runs/{run_id}/resume` | Ask adapter to resume a paused external task. |
| POST | `/internal/v1/data-sync/runs/{run_id}/cancel` | Ask adapter to cancel a nonterminal external task. |

Provider response fields: `provider_code`, `display_name`, `api_server_url`, `tenant_name`, `credential_status`, `adapter_version`, `status`, and adapter-supplied `query_schema`. Never return `tenant_id`, `tenant_key`, Token API URL, access token, or adapter factory. Plan response fields are plan ID/name/Provider/status/frequency/query/next and last run times/timestamps. Run response fields are the safe fields in the implementation plan; failure and result summaries are bounded and redacted.

`400/422` means malformed or schema-invalid input, `404` means unknown ID, `409` means state conflict, active-run deletion, or idempotency-key reuse with a different payload, and `503` means a configured Provider is unavailable. No user request can register Provider code or change adapter/tenant credentials.

## Idempotency And Migration Draft

- Plan creation: persist caller scope plus `Idempotency-Key` and a canonical payload digest. Reuse with identical input returns the same plan; reuse with different input returns 409.
- Manual run creation: key is scoped to plan and caller. Scheduled run creation uses a unique `(plan_id, scheduled_slot)` identity. Under a row lock, only one nonterminal run per plan can exist. Retry after a crash returns the same queued run.
- Run controls: persist action and idempotency key with audit; repeated identical requests return current run state. A 401 refreshes Token once, 408/429/5xx use bounded backoff, 409 invokes external-task lookup/recovery, and 422 is not retried.
- `data_sync_config` migration: UUID PK; unique idempotency scope/key; provider code, immutable name/frequency/query JSONB, plan status, next/last run timestamps, created/updated actor and timestamps, deleted timestamp. Index `(status, next_run_at)` for scheduler claim.
- `data_sync_run` migration: UUID PK and FK to plan with no cascade delete; provider code, adapter version, immutable query JSONB/hash, seven-state status, external task/request IDs, schedule slot, cursor, counts, control metadata, safe summaries, trace ID, claim owner/lease/heartbeat/retry timestamps and attempts, timestamps. Unique scheduled-slot identity and partial unique nonterminal-plan index. Preserve audit log as the control history.
- The stored query hash supports comparison and idempotency within a run; it is not a plan version. Secrets and large external response bodies never enter either table or audit summaries.

## Review Gates

| Gate | Evidence required before integration |
| --- | --- |
| Architecture | Catalog stays file-backed; adapter owns protocol and schema; no result sink or ingest coupling. |
| Data Model | Immutable plan fields, soft deletion, run FK/history, one nonterminal run per plan, no secret columns. |
| API Contract | Paths, schemas, 409/422 behavior, idempotency, auth, and safe Provider projection verified. |
| Permission And Audit | Auth required; plan/run mutations audited; credentials and responses redacted. |
| Version State | Plan and run transition tests; scheduled/manual creation excluded while paused/deleted. |
| Frontend UX | Separate plan and run controls with explicit disabled/conflict states. |
