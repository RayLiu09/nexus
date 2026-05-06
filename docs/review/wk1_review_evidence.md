# Week 1 Review Evidence

Task package: `docs/task-packages/wk_1_task_package.md`

## Review Gate Mapping

| Gate | Evidence |
|------|----------|
| API Contract Gate | `docs/contracts/p0_api_state_contract.md`, backend `/v1` route tests. |
| Data Model Gate | `nexus-app` SQLAlchemy models and Alembic migration for local identity, API callers, data sources, ingest batches, and raw objects. |
| Frontend UX Gate | `nexus-console` P0 routes and shared status label map. |
| Acceptance Gate | Backend pytest suite and `docs/testing/p0_e2e_checklist.md`. |

## Architecture Drift Checklist

| Check | Status | Notes |
|-------|--------|-------|
| No enterprise IAM dependency | Pass | Local org/user/API caller models only. |
| DingTalk not a runtime dependency | Pass | No DingTalk integration added. |
| No self-developed `llm-gateway` | Pass | No AI gateway page or service added. |
| Prompt management remains NEXUS-owned | Pass | Contract reserves `ai_prompt_profile`; no external prompt store added. |
| AI governance not independent service | Pass | No independent AI governance deployment added. |
| Governance input not raw object | Pass | Week 1 raw objects are ledger only; governance is not implemented. |
| No forbidden reverse pointers | Pass | Week 1 models do not introduce asset/version governance reverse pointers. |
| No P1/P2 page as P0 | Pass | NX-11 and NX-12 are not added as P0 console routes. |

## Review Correction: Package Ownership

Review feedback on 2026-05-03 clarified the repository ownership boundary:

- `nexus-app` carries NEXUS core backend/domain logic.
- `nexus-api` carries externally consumed business API service endpoints.

The Week 1 implementation was adjusted accordingly:

- Moved domain enums, settings, database setup, SQLAlchemy models, Pydantic domain schemas, CRUD/application services, and Alembic migration from `nexus-api` into `nexus-app`.
- Kept FastAPI app setup, route handlers, API envelopes, error handlers, request logging, and `trace_id` middleware in `nexus-api`.
- Removed direct Alembic ownership from `nexus-api`; the `nexus-api` lock may still include Alembic transitively because it depends on local editable `nexus-app`.
- Updated tests so `nexus-app` validates core model/service behavior and `nexus-api` validates API route registration/adaptation.

This avoids keeping core data asset platform logic in `nexus-api` and restores the intended ownership split.

## Environment Check From `.env.dev`

Non-destructive middleware checks were run with secrets redacted.

The `.env.dev` file loads successfully through `nexus-app` settings. PostgreSQL and MinIO are P0-required targets; Redis and RabbitMQ settings are present and reachable in this development environment but are v2.4 scale-up components, not P0 required dependencies. The checks below validate basic TCP/HTTP reachability only; they do not write data, run migrations, create buckets, or authenticate application-level operations.

| Component | Config Target | Check Result | Notes |
|-----------|---------------|--------------|-------|
| PostgreSQL | `10.100.11.182:5432`, db `nexus_dev`, user `postgre_normal` | TCP OK | `POSTGRES_DRIVER=postgresql` is normalized by code to SQLAlchemy runtime URL `postgresql+psycopg://...`. |
| Redis | `10.100.11.51:6379`, db `0` | TCP OK | v2.4 scale-up component only; no Redis password is configured in `.env.dev`. |
| RabbitMQ | `10.100.11.182:5672`, vhost `nexus`, user `rabbitmq_nexus` | TCP OK | v2.4 scale-up component only; `RABBITMQ_URL` and `CELERY_BROKER_URL` point to `/nexus`. |
| MinIO | `http://10.100.11.182:9000`, bucket `nexus-dev-objects` | S3 API OK | `head_bucket` passed. Upload checks passed for `raw/`, `staging/`, `parsed/`, `normalized/`, `export/`, and `.env.dev` extra partition `misc/`. |
| MinerU | `http://10.100.11.252:8000` | Connection refused | Service appears unreachable from this host at check time; requires service/process or endpoint review. |
| RAGFlow | `http://10.100.11.182:9380` | HTTP 404 | Host is reachable; root path is not a health endpoint. `RAGFLOW_API_KEY` is empty, so authenticated integration calls may fail. |
| LiteLLM | `http://10.100.11.51:4000` | HTTP 200 | Endpoint reachable. `LITELLM_API_KEY` is empty; confirm whether dev LiteLLM permits unauthenticated calls. |

Configuration gaps:

- `RAGFLOW_API_KEY` is empty.
- `LITELLM_API_KEY` is empty.
- MinerU endpoint currently refuses connection.
- MinIO unauthenticated root HTTP GET returns 403, but authenticated S3 API validation now passes for bucket access and partition uploads.

## Human Review Still Required

Week 1 implementation creates a reviewable baseline. Human owners still need to approve:

- final API naming before Week 2 parallel implementation;
- data model field names and uniqueness constraints;
- real business sample files, sample suitability, and desensitization after business expert review;
- frontend IA and status label wording.

## Pending Inputs

| Item | Status | Owner / Precondition |
|------|--------|----------------------|
| Real D1-D4 business samples | Pending | Business experts complete sample review and provide desensitized files or payloads. Current `docs/samples/p0_sample_inventory.md` contains placeholders only. |
| MinIO bucket-level validation | Done | Authenticated S3 API check on 2026-05-03 verified `head_bucket` plus `PUT -> HEAD -> GET` for `raw/`, `staging/`, `parsed/`, `normalized/`, `export/`, and `misc/`. |
| MinerU runtime endpoint | Blocked | `http://10.100.11.252:8000` refuses connections from this host; infrastructure owner must start service or confirm endpoint/port. |
| RAGFlow authenticated integration | Pending | Endpoint host responds, but root path returns 404 and `RAGFLOW_API_KEY` is empty. Need correct health/API path and dev API key if authentication is required. |
| LiteLLM authentication mode | Pending | Endpoint returns HTTP 200, but `LITELLM_API_KEY` is empty. Need confirmation whether dev LiteLLM permits unauthenticated calls. |

## Verification Run

Commands run on 2026-05-03:

| Command | Result | Notes |
|---------|--------|-------|
| `cd nexus-app && pytest` | Pass | 7 tests passed. Covers enum contract, `.env.dev` settings loading, core services, idempotency constraint, and checksum constraint. |
| `cd nexus-api && pytest` | Pass | 9 tests passed after ownership split. Covers API route registration/adaptation and route functions. |
| `cd nexus-api && python3 -m compileall nexus_api` | Pass | Python API package compiles. |
| `cd nexus-app && python3 -m compileall nexus_app` | Pass | Python core app package compiles. |
| `cd nexus-console && npm install` | Pass | Generated `package-lock.json`; Next upgraded to `16.2.4` after `16.0.0` security warning during earlier Week 1 setup. |
| `cd nexus-console && npm run build` | Pass | Next generated 14 app routes including all P0 placeholders. |
| `cd nexus-console && npm audit --json` | Residual risk | 2 moderate findings remain through Next's PostCSS dependency. NPM only offers a breaking downgrade to Next 9.3.3, so no compatible automated fix was applied. |
| `python3 -m nexus_app.scripts.check_env --env-file ../.env.dev` | Partial pass | Config loads and middleware targets are present. PostgreSQL, Redis, RabbitMQ, and LiteLLM are reachable; Redis/RabbitMQ are v2.4 scale-up components; MinIO/RAGFlow need endpoint-specific authenticated checks; MinerU refuses connection. |
| MinIO partition upload check with S3 API | Pass | `nexus-dev-objects` `head_bucket` passed. Test run `dac3e26206f1` uploaded and read back small JSON objects under `raw/_upload_check/`, `staging/_upload_check/`, `parsed/_upload_check/`, `normalized/_upload_check/`, `export/_upload_check/`, and `misc/_upload_check/`. |
| stale boundary scan with `rg` | Pass | No remaining imports from deleted `nexus_api.config/database/models/crud/enums`; no documentation claims `nexus-api` owns Week 1 models or Alembic migrations. |

## Test Environment Note

FastAPI HTTP client tests using `fastapi.testclient.TestClient` and `httpx.ASGITransport` hung in the current sandbox even for a minimal FastAPI app. To keep Week 1 verification repeatable, backend tests validate route registration, route functions, schemas, CRUD helpers, and SQLAlchemy constraints directly. Full HTTP contract tests should be re-enabled in an environment where the ASGI test client returns normally.
