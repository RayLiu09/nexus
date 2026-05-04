# Week 2 Review Evidence

Task package: `docs/task-packages/wk_2_task_package.md`

## Scope Implemented

Week 2 starts the M1 ingest-to-assetization loop:

- JSON/base64 file submit through `/v1/ingest/files`.
- Crawler package submit through `/v1/ingest/crawler-packages`.
- Raw object persistence abstraction for MinIO `raw/`.
- Job and job stage records for the M1 pipeline.
- Fake MinerU adapter for deterministic tests plus real MinerU `/file_parse` adapter and health boundary.
- Parse artifact records for document inputs.
- Normalized document / normalized record payloads written through `normalized_asset_ref`.
- Asset and version records for asset catalog and detail reads.
- Console M1 static views for workbench, ingest, raw ledger, jobs, assets, and asset detail.

## Review Gate Mapping

| Gate | Evidence |
|------|----------|
| API Contract Gate | `/v1/ingest/files`, `/v1/ingest/crawler-packages`, jobs, normalized refs, parse artifacts, assets, and versions route tests. |
| Data Model Gate | `nexus-app` models and Alembic migration `20260504_0002_week2_ingest_assetization.py`. |
| Version State Gate | Job status/stage tests and asset version `processing -> available` M1 transition tests. |
| Frontend UX Gate | `nexus-console` M1 views reuse shared status labels and P0 pages only. |
| Acceptance Gate | `docs/week2_runbook.md`, backend pytest suites, and M1 query path. |

## Architecture Drift Checklist

| Check | Status | Notes |
|-------|--------|-------|
| No enterprise IAM dependency | Pass | Week 2 continues to use local data source/user context only. |
| No self-developed `llm-gateway` | Pass | No LiteLLM gateway implementation or page added. |
| No independent AI governance service | Pass | AI governance remains out of Week 2 scope. |
| Raw object not used for official governance | Pass | Raw object feeds parsing/normalization only. |
| MinerU output not used as asset master data source | Pass | MinerU fake/adapter output is stored as `parse_artifact`; normalized ref is generated separately. |
| No forbidden reverse pointers | Pass | No `document_asset.current_version_id`, no `document_version.normalized_ref_id`, no `document_version.quality_report_id`. |
| `nexus-api` boundary preserved | Pass | API routes call `nexus-app.pipeline`; core logic stays in `nexus-app`. |

## Environment Evidence

| Component | Status | Notes |
|-----------|--------|-------|
| PostgreSQL | OK | User confirmed ready; Week 2 migration added for M1 objects. |
| MinIO | OK | Bucket and partition upload checks passed before Week 2 implementation. |
| MinerU | OK | TCP reachable; `/health`, `/docs`, and `/openapi.json` return HTTP 200. |

## Important Implementation Notes

- The public file submit endpoint currently accepts base64 content in JSON. This avoids adding multipart request coupling to the external `/v1` API while the internal MinerU adapter performs MinerU multipart integration.
- Tests default to `InMemoryObjectStorage` and `FakeMinerUAdapter` so M1 verification does not depend on large sample files or parser runtime variability. Runtime can use the real MinerU `/file_parse` adapter when `MINERU_USE_FAKE` is false.
- The S3 adapter uses `boto3` against MinIO but normalizes object-missing differences into `ObjectNotFoundError`; business code must not branch on AWS-specific `ClientError` text. Bucket-missing and permission errors stay as storage errors so environment or access problems are not mistaken for idempotent object absence.

## Verification Run

Commands run on 2026-05-04:

| Command | Result | Notes |
|---------|--------|-------|
| `cd nexus-app && pytest` | Pass | 17 tests passed. Covers Week 1 services, Week 2 pipeline, and MinIO/S3 missing-object normalization, including MinIO object 404 and missing-bucket separation. |
| `cd nexus-api && pytest` | Pass | 12 tests passed. Covers Week 1 routes and Week 2 route adaptation. |
| `cd nexus-app && python3 -m compileall nexus_app` | Pass | Core package compiles. |
| `cd nexus-api && python3 -m compileall nexus_api` | Pass | API package compiles. |
| `cd nexus-console && npm run build` | Pass | Next.js production build passed for all P0/M1 routes. |
| `git diff --check` | Pass | No whitespace errors. |
| Sensitive diff scan | Pass | No `.env.dev` secrets or middleware credentials found in staged worktree diff. |
| Forbidden pointer scan | Pass | No active model, schema, migration, or API fields for forbidden reverse pointers. |

Additional development-environment evidence on 2026-05-05:

| Check | Result | Notes |
|-------|--------|-------|
| Alembic initialization | Pass | `nexus_dev` upgraded to `20260504_0002 (head)`. |
| Live-commerce sample E2E | Pass | `docs/samples` live-commerce textbook content ingested with safe UTF-8 business filename `live-commerce-textbook.docx`. |
| E2E database state | Pass | Batch `completed`, raw object `raw_persisted`, job `succeeded`, asset/version `available`, parse artifact/ref `generated`. |
| E2E MinIO readback | Pass | Raw object 11,400,205 bytes, parsed artifact 2,107,170 bytes, normalized document 645 bytes all read back from MinIO. |

E2E object IDs:

- `ingest_batch`: `81116c57-ba5e-4c26-886a-d1bf645c6f36`
- `raw_object`: `b746363c-2c17-4bc6-b558-2acc943c0e26`
- `job`: `4f526826-0ad8-4165-80eb-05450c63e038`
- `document_asset`: `7936f89c-d618-457e-b97d-55340c608cc8`
- `document_version`: `c310a615-b530-422b-880f-6278e328f10b`
- `parse_artifact`: `695b9983-e153-4f37-bb5f-0296a1afa77d`
- `normalized_asset_ref`: `6b57bb24-108f-4404-abb2-06167af1c9fd`

## Remaining Work

- Run real reviewed business samples through the MinerU `/file_parse` adapter and calibrate parsing options if needed.
- Run Alembic migration against the shared development PostgreSQL database.
- Replace console static M1 data with API calls after the development API server is deployed.
- RAGFlow indexing, AI governance, rule guardrails, search, QA, and permission audit are later stages.
