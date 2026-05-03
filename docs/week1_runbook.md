# Week 1 Runbook

Source task package: `docs/task-packages/wk_1_task_package.md`

## Backend Core

`nexus-app` owns core domain settings, database setup, SQLAlchemy models, Alembic migrations, Pydantic domain schemas, and reusable application services.

Run core tests:

```bash
cd nexus-app
pytest
```

Check `.env.dev` middleware targets without printing secrets:

```bash
cd nexus-app
python -m nexus_app.scripts.check_env --env-file ../.env.dev
```

Run migrations against the configured database when the development database is available:

```bash
cd nexus-app
alembic upgrade head
```

## Business API

`nexus-api` owns only the externally consumed `/v1` FastAPI service layer. It imports core models, schemas, settings, database sessions, and application services from `nexus-app`.

Run tests:

```bash
cd nexus-api
pytest
```

Start API:

```bash
cd nexus-api
uv run uvicorn nexus_api.main:app --reload
```

Week 1 implemented routes:

- `GET /v1/health`
- `GET /v1/runtime/state`
- `POST /v1/org-units`
- `GET /v1/org-units`
- `GET /v1/org-units/{org_unit_id}`
- `POST /v1/users`
- `GET /v1/users`
- `GET /v1/users/{user_id}`
- `POST /v1/api-callers`
- `GET /v1/api-callers`
- `GET /v1/api-callers/{api_caller_id}`
- `POST /v1/data-sources`
- `GET /v1/data-sources`
- `GET /v1/data-sources/{data_source_id}`
- `POST /v1/ingest/batches`
- `GET /v1/ingest/batches`
- `GET /v1/ingest/batches/{batch_id}`
- `POST /v1/raw-objects`
- `GET /v1/raw-objects`
- `GET /v1/raw-objects/{raw_object_id}`

## Frontend

Install and start:

```bash
cd nexus-console
npm install
npm run dev
```

P0 routes:

- `/login`
- `/workbench`
- `/data-sources`
- `/ingest`
- `/raw-ledger`
- `/jobs`
- `/assets`
- `/assets/demo-asset`
- `/governance`
- `/rules`
- `/iam-audit`
- `/ai-prompts`

## Verification Notes

- Backend tests do not require external PostgreSQL; they use in-memory SQLite for Week 1 constraints.
- Runtime defaults are loaded from the repository root `.env.dev` style variables by `nexus-app`.
- Frontend build requires installing Next.js dependencies.
- No enterprise IAM, DingTalk runtime dependency, self-developed AI gateway, or P1/P2 route is included.
