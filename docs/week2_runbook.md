# Week 2 Runbook

Source task package: `docs/task-packages/wk_2_task_package.md`

## Goal

M1 demonstrates the minimum ingest-to-assetization loop:

```text
ingest submit
  -> ingest_batch
  -> raw_object in MinIO raw/
  -> job and job_stage
  -> parse_artifact in parsed/ for documents
  -> normalized_asset_ref in normalized/
  -> document_asset / document_version marked ready for governance
```

AI governance, rules, RAGFlow indexing, search, QA, and full permission audit remain out of scope for Week 2. Therefore M1 does not officially admit versions into `available`; it leaves asset/version state as `processing` with `metadata_summary.m1_ready_for_governance=true` for Week 3/4 governance and rule decisions.

## Backend

Run core tests:

```bash
cd nexus-app
pytest
```

Run API tests:

```bash
cd nexus-api
pytest
```

Run migrations:

```bash
cd nexus-app
alembic upgrade head
```

Start API:

```bash
cd nexus-api
uv run uvicorn nexus_api.main:app --reload
```

## M1 API Path

Submit a file-style payload:

```http
POST /v1/ingest/files
```

The request uses a JSON body with `content_base64` to keep the `/v1` API stable while the internal MinerU adapter handles multipart integration separately.

Submit a crawler JSON package:

```http
POST /v1/ingest/crawler-packages
```

Query M1 outputs:

- `GET /v1/raw-objects`
- `GET /v1/ingest/batches/{batch_id}/raw-objects`
- `GET /v1/jobs`
- `GET /v1/jobs/{job_id}/stages`
- `GET /v1/parse-artifacts`
- `GET /v1/normalized-refs`
- `GET /v1/assets`
- `GET /v1/assets/{asset_id}`
- `GET /v1/assets/{asset_id}/versions`
- `GET /v1/audit-logs`

Raw object ledger creation is not a public API. `POST /v1/raw-objects` is intentionally absent; raw rows are written only by the storage-backed ingest submission flow.

## Console Live API Path

`nexus-console` uses live `/v1` API data for the Week 1/2 pages:

- `/workbench`
- `/data-sources`
- `/ingest`
- `/raw-ledger`
- `/jobs`
- `/assets`
- `/assets/{asset_id}`
- `/iam-audit`

Configure the Console API base URL with `NEXUS_API_BASE_URL`; it defaults to `http://127.0.0.1:8000`.

Start Console:

```bash
cd nexus-console
NEXUS_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Run the Week 1/2 Console connectivity check after API and Console are running:

```bash
NEXUS_API_BASE_URL=http://127.0.0.1:8000 \
NEXUS_CONSOLE_BASE_URL=http://127.0.0.1:3000 \
scripts/week2_console_e2e.sh
```

The script creates local org/user/API caller/data source through `/v1`, submits a small text ingest through `/v1/ingest/files`, verifies raw object, job stages, asset detail, normalized ref, audit logs, and confirms the Console pages render those live objects.

## Environment

The development environment checks completed before this implementation:

- PostgreSQL is reachable.
- MinIO bucket `nexus-dev-objects` exists and accepts uploads under `raw/`, `staging/`, `parsed/`, `normalized/`, `export/`, and `misc/`.
- MinerU API is reachable at `http://10.100.11.252:8000`; `/health`, `/docs`, and `/openapi.json` return HTTP 200.

Week 2 tests use in-memory storage and a fake MinerU adapter for deterministic verification. Runtime file ingest uses the real MinerU `/file_parse` adapter when `MINERU_ENDPOINT` is configured and `MINERU_USE_FAKE` is false. The real MinIO adapter is implemented through S3-compatible `boto3`, with provider-specific missing-object responses normalized into NEXUS `ObjectNotFoundError`.

## Boundaries

- `nexus-app` owns domain models, migrations, object storage, parsing adapter boundary, pipeline services, and tests.
- `nexus-api` owns only the externally consumed `/v1` route layer.
- Do not add `document_asset.current_version_id`.
- Do not add `document_version.normalized_ref_id`.
- Do not add `document_version.quality_report_id`.
- Do not treat raw object or MinerU raw output as official governance input.
- Do not use `POST /v1/raw-objects` as a public ingest path; raw objects must be created through storage-backed ingest submission.
- Official `available` requires Week 3/4 quality, AI governance, rules, and uniqueness decisions. M1 readiness is not the same as production availability.
