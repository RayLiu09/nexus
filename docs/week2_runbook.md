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
  -> document_asset / document_version
```

AI governance, rules, RAGFlow indexing, search, QA, and full permission audit remain out of scope for Week 2.

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
- `GET /v1/jobs`
- `GET /v1/jobs/{job_id}/stages`
- `GET /v1/parse-artifacts`
- `GET /v1/normalized-refs`
- `GET /v1/assets`
- `GET /v1/assets/{asset_id}`
- `GET /v1/assets/{asset_id}/versions`

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
