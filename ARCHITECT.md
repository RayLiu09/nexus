# NEXUS Architecture Contract v3.0

This document is the concise architecture baseline for implementation. It is distilled from `docs/企业数据与知识资产平台技术选型和架构nexus_v3.0.md` (v2.6, v2.5, v2.4 archived).

## Key Changes in v3.0

| Change | v2.6 | v3.0 |
|--------|------|------|
| `ingest_validate` job type | Not defined; validation implicit in gateway | Explicit `ingest_validate` job stage; writes `INGEST_VALIDATE_COMPLETED` / `INGEST_VALIDATE_FAILED` audit events |
| assetize vs normalize | Both labeled "normalize" loosely | **assetize** = create asset/asset_version anchor (job-orchestrator + metadata-service); **normalize** = content standardization contract (normalize-service). Distinct stages with distinct responsibilities. |
| MinerU model_version | Hardcoded `hybrid-auto-engine` | Auto-selected by mime_type: HTML → `MinerU-HTML`; default → `pipeline`; complex layout → `vlm` (opt-in). Caller can override via `Job.payload.model_version_override`. |
| MinerU OCR | No explicit control | Auto-enabled for `image/*`, `application/pdf`, `tiff` mime types |
| MinerU image output | Not stored | Images extracted from ZIP response, stored at `parsed/<version_id>/<artifact_id>/images/<name>`; URIs recorded in `parse_artifact.metadata_summary.image_uris` and `normalized_asset_ref.lineage.image_uris` |
| MinerU cluster | Single node only | CPU Worker group (pipeline model) + GPU Worker group (vlm/MinerU-HTML) + MinerU Router; cluster scale-up triggers documented |
| normalize-service mechanism | Not specified | LLM semantic extraction + rule-engine fallback validation (dual-layer); rules defined by domain experts |
| `normalized_asset_ref` fields | `block_count`, `record_count`, `metadata_summary` only | Added: `source_type`, `content_type`, `title`, `language`, `governance` (JSONB), `quality` (JSONB), `lineage` (JSONB) |
| `governance_result` target | Implicitly `asset_version` | Explicitly `normalized_asset_ref`; `knowledge_chunk.normalized_ref_id` links chunk to normalized ref |
| Auto-tagging subject | Implied from chunks/asset | `metadata_enrich` targets **normalized assets**; chunks do not exist yet at tag generation time |
| Auto-tagging admission | All tags go to draft queue | High-confidence tags auto-committed (audit logged); low-confidence tags enter human review queue |
| Knowledge Pipeline | Coupled to Asset Pipeline | **Decoupled**: Knowledge Pipeline is independent, triggered by `normalized_asset_ref`; P0 scope = Pipeline 1 (RAG retrieval KB) only |

## Architecture Goal

NEXUS is an enterprise data and knowledge asset platform for D1-D4 pilot domains. It provides controlled ingestion, raw retention, parsing, standardization, AI-led metadata governance, rule guardrails, quality scoring, RAGFlow indexing, permission-filtered search/QA, audit, and API exposure.

## System Boundaries

| Component | Responsibility | Explicitly Not Responsible For |
|-----------|----------------|-------------------------------|
| NEXUS | Asset master data, versions, governance, rules, jobs, permissions, audit, console, APIs | OCR/layout internals, vector engine internals, enterprise-wide IAM |
| `identity-org-service` | Local org units, users, roles, API callers, org scopes | Enterprise IAM or company-wide identity governance |
| DingTalk adapter | Optional department/user sync | Runtime dependency or permission decision authority |
| MinerU | PDF/Office/image/scanned-document parsing; image extraction | Asset governance, permissions, indexes |
| LiteLLM | Existing AI gateway: model routing, provider adaptation, credentials, gateway-side limits | NEXUS Prompt versions, governance states, asset master data |
| `metadata-service.ai-governance` | Internal AI governance submodule: Prompt/profile management, LiteLLM calls, AI suggestions, quality scoring | Independent deployment, bypassing rule guardrails |
| RAGFlow | Chunking execution, index construction, retrieval execution | NEXUS master data, permissions, audit authority |
| Crawler systems | Dynamic data source push | Governance, index governance, permissions |
| Upper systems | Consume NEXUS APIs | Direct calls to MinerU, RAGFlow, LiteLLM, or internal DBs |

## Design Principles

- Control plane and execution plane are separated.
- Raw data is persisted before processing.
- Governance happens after standardization, not before.
- Master data is separated from execution projections.
- Derivable relations are not stored as reverse pointers.
- Automation is the default; manual review is exception handling.
- Classification, level, tags, org scope, quality admission, review triggers, and index admission are configurable rules.
- Imported data sources default to L1/L2; L3/L4 must be explicitly configured, rule-evidenced, or manually/security approved and audited.
- AI leads semantic understanding and scoring; rules are hard guardrails; humans handle exceptions, samples, and feedback.
- AI output must be explainable, structured, schema-valid, evidence-backed, and auditable.
- Models are replaceable through LiteLLM aliases; NEXUS owns output schemas.
- Local identity is the baseline; DingTalk sync is optional.
- P0 reserves operations extension points but does not productize an operations center.
- Right-size by scale: use minimum viable infrastructure in P0; each simplified capability has a documented upgrade trigger and migration path.
- `raw_object` is the unified raw retention model for all sources (binary files and serialized JSON packages).
- Processing pipeline is determined at job creation, not at runtime inference.
- **assetize** builds the master data anchor; **normalize** converts content to the standard contract. These are distinct stages.
- `normalize-service` uses LLM semantic extraction + rule-engine fallback validation (dual-layer).
- MinerU is called with auto-selected `model_version` and `ocr_enable`; images are stored alongside the JSON result.
- Knowledge Pipeline is independent of Asset Pipeline; they connect only through `normalized_asset_ref`.

## Logical Layers

1. **Source and access layer**: console, API callers, crawler push, NAS/batch upload.
2. **Raw persistence layer**: MinIO `raw/`, `staging/`, `parsed/` (including `images/` sub-directories), `normalized/`; PostgreSQL ledgers and checksums.
3. **Job and processing layer**: `job-orchestrator`, PostgreSQL job queue + Worker poller (P0) / RabbitMQ + Celery (scale-up). Both pipelines include: `ingest_validate` → `assetize` → parse (A only) → `normalize`.
4. **Standardization and governance layer**: `normalize-service` (LLM extraction + rule fallback), `normalized_document`, `normalized_record`, `normalized_asset_ref` (with full governance/quality/lineage fields), `metadata-service.ai-governance`, `metadata_enrich`, `governance-rule`.
5. **Master data layer**: `metadata-service` for assets, versions, governance results (embedded `quality_summary` and `decision_trail`), read models.
6. **Index, permission, and service layer**: `ragflow-adapter`, RAGFlow, `search-service`, `iam-audit-service`, `nexus-api`.
7. **Knowledge Pipeline layer** (independent): input = `normalized_asset_ref`; P0 scope = Pipeline 1 (RAG retrieval KB) only.

## Two Processing Pipelines

Pipeline routing stored in `Job.payload.pipeline_type` at job creation. Workers read from payload; no runtime inference.

| `DataSource.source_type` | `raw_object.mime_type` | `pipeline_type` |
|--------------------------|------------------------|-----------------|
| `file_upload`, `nas` | non-`application/json` | `"document"` |
| `file_upload`, `nas` | `application/json` | `"record"` |
| `crawler`, `database`, `webhook` | any | `"record"` |

**Pipeline A — Document Processing:**

Stages: ingest → `ingest_validate` → `assetize` → **parse** (MinerU → `parse_artifact` + images) → **normalize** (`normalized_document`) → govern → index.

Key rule: `run_parse()` auto-selects `model_version` from `raw_object.mime_type`, auto-enables OCR for image/pdf/tiff, stores images at `parsed/<version_id>/<artifact_id>/images/`.

Produces: `parse_artifact`, `normalized_asset_ref(type=document)`.

**Pipeline B — Record Processing:**

Stages: ingest → `ingest_validate` → `assetize` → **normalize** (`normalized_record`) → govern → index. **No MinerU, no `parse_artifact`.**

Produces: `normalized_asset_ref(type=record)`.

**Shared by both pipelines:**
- Same `asset`/`asset_version` model (distinguished by `asset_kind`).
- Same version state machine.
- Required audit events: `INGEST_BATCH_SUBMITTED`, `RAW_OBJECT_PERSISTED`, `INGEST_VALIDATE_COMPLETED`, `VERSION_STATUS_CHANGED`, `PIPELINE_FAILED`.

## assetize vs normalize Stages

| Stage | Owner | Responsibility | Rules |
|-------|-------|----------------|-------|
| **assetize** | `job-orchestrator` + `metadata-service` | Create `asset`/`asset_version` master data anchor via `(data_source_id, source_object_key)` idempotency | Same key + same checksum → skip; same key + different checksum → archive old available version, create version_no+1; different key → new asset |
| **normalize** | `normalize-service` | Convert MinerU artifacts or raw JSON to unified standard asset contract | Rules defined by domain experts; executed via LLM semantic extraction (content understanding, field filling, language detection) + rule-engine fallback validation (required fields, format constraints, classification compliance) |

`asset_version.id` established by assetize is the anchor for all downstream artifacts (`parse_artifact`, `normalized_asset_ref`, `governance_result`, `knowledge_chunk`).

## MinerU Calling Contract

**model_version selection:**

| mime_type | model_version | Notes |
|-----------|--------------|-------|
| `text/html`, `application/xhtml+xml` | `MinerU-HTML` | Must be explicit |
| default (PDF, Word, PPT, images) | `pipeline` | Low cost, high throughput |
| complex layout / mixed graphics (opt-in) | `vlm` | Higher GPU cost; trigger via `Job.payload.model_version_override` |

**OCR auto-enable:** enabled for `image/*`, `application/pdf`, `tiff`; disabled for all other types.

**Image storage:** MinerU called with `return_images=true, response_format_zip=true`. ZIP unpacked:
- JSON → `parsed/<version_id>/<artifact_id>/mineru-result.json`
- Images → `parsed/<version_id>/<artifact_id>/images/<image_name>`

`parse_artifact.metadata_summary` records `model_version`, `ocr_enabled`, `image_count`, `image_uris`.
`normalized_asset_ref.lineage` records `image_uris` for downstream rendering.

**Cluster extension points (pre-reserved, not P0 required):**
- CPU Worker group for `pipeline` model tasks.
- GPU Worker group for `vlm`/`MinerU-HTML` tasks (GPU isolated).
- MinerU Router for health check and load distribution; task state managed externally by NEXUS job center.
- Scale trigger: parse queue P95 wait > 20 min for 3 days, or GPU utilization peak > 80% sustained.

## Core Domain Objects

- Identity: `org_unit`, `user_account`, `api_caller`.
- Ingestion: `data_source`, `ingest_batch`, `raw_object`.
- Asset master data: `asset` (table: `document_asset`, pending migration), `asset_version` (table: `document_version`, pending migration).
- Parsing: `parse_artifact` (Pipeline A only).
- Standardization: `normalized_asset_ref`, `normalized_document`, `normalized_record`.
- AI governance: `ai_prompt_profile`, `ai_governance_run`.
- Rules and governance result: `governance_rule_set`, `governance_rule`, `governance_result` (embedded `quality_summary` + `decision_trail`).
- Knowledge and index: `knowledge_chunk`, `index_manifest`.
- Jobs and audit: `job`, `job_stage`, `audit_log`.

## normalized_asset_ref Fields (v3.0)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | PK |
| `version_id` | string | yes | FK → `asset_version.id` |
| `normalized_type` | enum | yes | `document` / `record` |
| `object_uri` | string | yes | MinIO path |
| `schema_version` | string | yes | Contract version |
| `checksum` | string | yes | SHA-256 |
| `status` | enum | yes | `generated` / `failed` / `deprecated` |
| `block_count` | int | yes | — |
| `record_count` | int | yes | — |
| `source_type` | string | no | Copied from raw_object for fast filtering |
| `content_type` | string | no | `document`/`slide_deck`/`table_sheet`/`web_record`/`media_meta` |
| `title` | string | no | Asset title |
| `language` | string | no | Primary language code, default `zh-CN` |
| `governance` | JSONB | yes | Classification, sensitivity level, org_scope, version_status snapshot |
| `quality` | JSONB | yes | Quality scores, anomaly items, manual review status |
| `lineage` | JSONB | yes | raw_object_id, parse_artifact_id, image_uris, processing chain trace |
| `metadata_summary` | JSONB | yes | Source, business, temporal metadata for search enrichment |

## Modeling Constraints

- `asset` does not store `current_version` (read model only, not a stored pointer).
- `asset_version` does not store `normalized_ref` (single-direction: `normalized_asset_ref.version_id → asset_version`).
- `governance_result` embedded JSONB: `quality_summary` + `decision_trail`. Do not extract to independent entities until the upgrade trigger is met.
- **`governance_result` target is `normalized_asset_ref`, not `asset_version`.**
- **`knowledge_chunk.normalized_ref_id` links chunks to `normalized_asset_ref`**, enabling traceability from chunk to standardized asset.
- Use read models (`asset_current_version_view`, `version_current_normalized_ref_view`) to express current state.

## Version State Contract

| Status | Meaning | Searchable |
|--------|---------|-----------|
| `processing` | Ingest, parse, standardize, govern, or index in progress | No |
| `available` | Passed admission; serves authorized users | Yes |
| `review_required` | Needs manual review | No |
| `archived` | Replaced historical version | No (default) |
| `disabled` | Manually disabled | No |
| `failed` | Unrecoverable failure | No |

`available` requires: effective `normalized_asset_ref`; `governance.quality_level = pass`; required classification, level, tags, org_scope populated; no blocking rule; sufficient AI confidence; uniqueness (no other available version, or old version archived atomically).

## Audit Event Contract

| Event | Trigger | Pipelines |
|-------|---------|-----------|
| `IngestBatchSubmitted` | Batch submitted | A / B |
| `RawObjectPersisted` | Raw object written to MinIO | A / B |
| `IngestValidateCompleted` | ingest_validate job succeeded | A / B |
| `IngestValidateFailed` | ingest_validate job failed | A / B |
| `CrossSourceDuplicateDetected` | Same checksum in different data_source | A / B |
| `VersionStatusChanged` | asset_version status transition | A / B |
| `AssetVersionArchived` | Old version archived by re-ingest | A / B |
| `PipelineFailed` | Any stage non-retryable failure | A / B |
| `DataSourceCreated` | Data source registered | — |
| `DataSourceStatusChanged` | Data source status change | — |
| `ApiCallerCreated` | API key created | — |
| `ApiCallerRevoked` | API key revoked | — |
| `AssetVersionAccessed` | api_caller or user accessed an asset version via `/v1` API | — |
| `SearchQueryExecuted` | Search query executed; records caller_id, query hash, hit normalized_ref_ids | — |
| `QAAnswerGenerated` | QA answer generated; records caller_id, question hash, cited normalized_ref_ids and chunk_ids | — |

**Consumption-side audit event field contract:**

`AssetVersionAccessed`: `caller_id`, `caller_type` (api_caller / user), `asset_id`, `version_id`, `normalized_ref_id`, `access_type` (read / search_hit / qa_citation), `trace_id`.

`SearchQueryExecuted`: `caller_id`, `caller_type`, `query_hash` (SHA-256 of query text, not plaintext), `hit_normalized_ref_ids` (list), `hit_count`, `data_source_ids` (distinct), `trace_id`.

`QAAnswerGenerated`: `caller_id`, `caller_type`, `question_hash` (SHA-256), `cited_normalized_ref_ids` (list), `cited_chunk_ids` (list), `answer_confidence`, `trace_id`.

These three events are the foundation for Phase 2 consumption-side data lineage analysis. They must be written by `nexus-api` search/QA handlers before returning results. Logs must not contain query plaintext, answer content, or L3/L4 data.

## Auto-Tagging Contract

- `metadata_enrich` targets **normalized assets** (`normalized_document` / `normalized_record`). Chunks do not exist yet at tag generation time.
- High-confidence tags (≥ threshold): auto-committed to `metadata-service`, audit log written. Admins can retrospectively review and revoke.
- Low-confidence tags (< threshold): queued for human review (confirm / revise / reject).
- All tag commit and override actions write audit logs.

## Knowledge Pipeline Boundary

```
Asset Pipeline → normalized_asset_ref (stable contract)
                        ↓ (trigger: normalized_asset_ref.status = generated)
              Knowledge Pipeline (independent, per-scenario)
                  P0: Pipeline 1 (RAG retrieval KB via ragflow-adapter → RAGFlow)
                  Later: Pipeline 2 (QA corpus), Pipeline 3 (process corpus),
                         Pipeline 4 (knowledge graph), Pipeline 5 (eval standard)
```

- Knowledge Pipeline inputs are exclusively `normalized_asset_ref` objects. Raw files, raw JSON, and MinerU output are not valid inputs.
- Each knowledge scenario has independent scheduling, rules, and human review flows; no cross-scenario dependency.
- P0 scope: Pipeline 1 only. Pipelines 2–5 are reserved architecture extension points.

## Core Flows

**Pipeline A (Document):**
`upload → raw_object (binary) → ingest_validate → Job(pipeline_type="document") → assetize (asset/asset_version) → MinerU parse (parse_artifact + images) → normalize (normalized_document) → normalized_asset_ref → AI governance → rules → governance_result → available/review_required → RAGFlow index`

**Pipeline B (Record):**
`crawler/webhook/batch → raw_object (JSON) → ingest_validate → Job(pipeline_type="record") → assetize (asset/asset_version) → normalize (normalized_record) → normalized_asset_ref → AI governance → rules → governance_result → index`

**Retrieval and QA:**
`caller/user context → auth verify (RBAC + org scope) → search-service → RAGFlow retrieval → org scope and level check → rerank/context → answer with source citations → audit`

**Reprocess and re-governance:**
Rule change, Prompt update, parse failure, index failure, manual review, or score calibration may trigger reprocess, re-governance, AI re-score, or index rebuild. All flows must be idempotent and auditable.

## Ingest Layer Architecture

The ingest gateway uses the `IngestAdapter` protocol:

- `PreparedContent`: `content`, `filename`, `mime_type`, `source_uri`, `raw_metadata`, `batch_summary`, `source_object_key`.
- `IngestAdapter` protocol: `data_source_id`, `idempotency_key`, `owner_user_id`, `prepare() → PreparedContent`.
- `submit_file_bytes()` for multipart uploads: bypasses base64 encoding, accepts raw bytes directly.

Storage key naming:
```
raw/<source_type>/<source_id>/<YYYY>/<MM>/<DD>/<idempotency_key>/<checksum_prefix>/<filename>
parsed/<version_id>/<artifact_id>/mineru-result.json
parsed/<version_id>/<artifact_id>/images/<image_name>
normalized/<normalized_type>/<version_id>/<ref_id>/schema-v1/<checksum_prefix>.json
```

Idempotency:
- Same `(data_source_id, idempotency_key)` → return existing batch.
- Same `data_source_id` + same `checksum` → `DUPLICATE_SKIPPED`.
- Different `data_source_id` + same `checksum` → `CrossSourceDuplicateDetected` audit, ingestion continues.
- Same `source_object_key` + different `checksum` → new `asset_version`, old available archived.

## PostgreSQL Worker Poller Contract

- Claim: `FOR UPDATE SKIP LOCKED`, ordered `priority ASC, created_at ASC` (**lower value = higher priority**; e.g., 10 > 100 > 200).
- Heartbeat every 30-60 s; timed-out jobs returned to `queued` (if retries remain) or `dead_lettered`.
- Retry backoff: 60 s, 300 s, 900 s. Default `max_attempts = 3`.
- LISTEN/NOTIFY: `pg_notify('nexus_jobs')` on ingest commit; `JobNotifier` wakes Workers immediately. SQLite falls back to polling.
- Partial index: `WHERE status = 'queued'` on `(next_run_at, priority, created_at)`.

Single-node capacity (16 Core / 64 GB / 48 GB GPU):

| Concurrency Item | Recommended | P0 Limit |
|-----------------|-------------|----------|
| Active pipeline jobs | 8-12 | 16 |
| MinerU parse jobs (Pipeline A) | 2-4 | 4 |
| Standardization jobs (Pipeline B) | 4-8 | 8 |
| AI governance / quality jobs | 2-4 | 6 |
| RAGFlow sync jobs | 2-4 | 6 |

## AI Governance Architecture

- NEXUS does not build `llm-gateway`; uses existing LiteLLM.
- `ai_prompt_profile` is P0: save-to-activate, auto-increment version, old version archived. No draft state.
- Governance input must be `normalized_document` or `normalized_record` (accessed via `normalized_asset_ref`). Raw files and raw JSON are not valid inputs.
- AI output pipeline: schema validation → field whitelist → redaction policy → rule guardrails → confidence threshold → state-machine decision.
- L3/L4 plain text must not reach external models unless using an approved private LiteLLM alias or explicit security exception.

## Rule Governance Architecture

- P0: PostgreSQL config tables + restricted JSON expression evaluator.
- Save-to-activate: rule set `version` auto-increments on each save. No draft state.
- Rule types: classification inference, level override, tag suggestion/restriction, org scope inference, sensitive admission, quality admission, manual review trigger, index admission.
- Conflict resolution (fixed, not configurable in P0): level → L4 > L3 > L2 > L1; classification/tag → highest-priority rule wins; org scope → narrower scope wins, irresolvable → `review_required`.

## Technology Baseline

| Area | P0 Baseline | Scale-Up Path |
|------|-------------|---------------|
| API/control plane | Python 3.11, FastAPI 0.115+, Pydantic v2 | — |
| Python deps | uv, `pyproject.toml`, `uv.lock` | — |
| Persistence | PostgreSQL 15+, SQLAlchemy 2.x, Alembic | — |
| Object storage | MinIO | — |
| Cache | In-process TTL cache | Redis 7.x |
| Async jobs | PostgreSQL job table + Worker poller | RabbitMQ + Celery |
| Frontend | React 19, Next.js 16 App Router, TypeScript | — |
| Charts | ECharts 5.x | — |
| Parsing | MinerU (pipeline / vlm / MinerU-HTML, auto-selected) | MinerU cluster (CPU + GPU Worker groups) |
| AI gateway | Existing LiteLLM | — |
| Search/index | RAGFlow | — |
| Embedding/rerank | `bge-large-zh-v1.5`, `bge-reranker-large` | — |

## Security and Audit

- P0: RBAC + org scope filtering + data level visibility check (L3/L4 requires explicit role grant).
- Imported data sources default L1/L2. L3/L4 is an exception requiring evidence and audit.
- ABAC is an architecture extension point, not P0.
- Cross-org access denied by default.
- API keys: scope, quota, `expired_at` revocation, audit.
- Rule expressions cannot execute arbitrary code.
- Logs must not expose sensitive fields, API keys, or large raw content.
- Every mutation of Prompt config, rules, version status, governance result, permissions, API keys, AI adoption, or human override must write audit logs.

## Alembic Migration Chain

```
20260501_0001 → 20260504_0002 → 20260506_0003 → 20260506_0004 → 20260506_0005
  → 20260507_0006 → 20260507_0007 → 20260508_0008 → 20260513_0009
  → [pending] asset_rename_migration (document_asset → asset table rename)
  → [pending] pipeline_type_in_job_payload
  → [pending] asset_source_object_key_uniqueness
```

## Scale-Up Triggers

| Simplified Capability | Upgrade Trigger |
|-----------------------|-----------------|
| `quality_summary` as embedded JSONB | Need independent quality history queries, compliance audit, or quality workflow |
| `decision_trail` as embedded JSONB | Need per-rule hit rate analysis, AI acceptance rate stats, or compliance audit |
| `ai_prompt_profile` save-to-activate | Multi-person Prompt review, approval workflow, or gray release |
| Rule save-to-activate | Rule change approval flow, time-window rollback, or gray release |
| PostgreSQL job queue | Active jobs > 16 sustained, queue wait P95 > 5 min for 3 days, or routing/dead-letter needs exceed PG poller |
| In-process cache | Horizontal scaling, distributed cache invalidation, or distributed locks |
| ABAC extension | Cross-org sharing, temporary approval, or attribute-based dynamic permissions |
| Default L1/L2 source level | Source approved to contain L3/L4 data with explicit review, masking, and audit |
| MinerU single node | Parse queue P95 > 20 min for 3 days, or GPU utilization peak > 80% sustained |
| Knowledge Pipeline 1 only | Need QA corpus, process corpus, knowledge graph, or evaluation standard library |
| `document_asset`/`document_version` table names | Execute v2.6 M15 migration |
| Consumption-side audit events only | Need downstream dependency graph, impact analysis, or data lineage visualization across systems |

## Consumption-Side Data Lineage Extension Point

> **Phase 2 extension — not P0/P1 required. Foundation is the three consumption-side audit events above.**

### Problem

The current `normalized_asset_ref.lineage` field covers production-side lineage only:
`raw_object → parse_artifact → normalized_asset_ref → knowledge_chunk`

It does not capture who consumed the asset, through which system, or what downstream business processes depend on it. When an asset is updated, deprecated, or reclassified, there is no mechanism to identify affected callers or assess impact.

### Phase 2 Capability Scope

When the following trigger is met — **consumption-side audit event volume reaches a level where manual impact assessment becomes impractical, or a governance/compliance requirement mandates downstream traceability** — implement:

**1. Consumption lineage read model (`asset_consumption_lineage`)**

Materialized from `AssetVersionAccessed`, `SearchQueryExecuted`, `QAAnswerGenerated` audit events. Fields:
- `normalized_ref_id` → `caller_id` + `caller_type` + `last_accessed_at` + `access_count`
- `asset_id` → distinct `caller_ids` + `data_source_ids` touched

**2. Downstream dependency query APIs**

```
GET /v1/assets/{id}/downstream-callers
  → list of api_callers that accessed this asset (from audit events)

GET /v1/api-callers/{id}/asset-dependencies
  → list of assets accessed by this caller (from audit events)

GET /v1/assets/{id}/impact-analysis
  → { affected_callers, affected_search_sessions, last_access_at, risk_level }
```

**3. Full lineage graph**

Merge production-side lineage (`raw_object → parse_artifact → normalized_asset_ref → chunk`) with consumption-side lineage (`chunk → search/QA → api_caller → business system`) into a unified directed graph, queryable per asset and visualizable in the asset detail page.

### Design Constraints

- The read model is derived from audit events; it does not require `api_caller` to explicitly register asset subscriptions (business systems cannot reliably self-report dependencies).
- Query plaintext and answer content must never be stored; only hashes and `normalized_ref_id` references.
- The lineage graph is eventually consistent; real-time accuracy is not required.
- Phase 2 implementation must not modify the `audit_log` schema; it reads from existing events.

### Upgrade Trigger

Activate Phase 2 when: governance or compliance requires downstream impact assessment before asset deprecation, OR manual impact analysis takes > 30 min per asset change, OR audit event volume for consumption events exceeds 10k/day.

## P0 Architecture Acceptance

- Both pipelines (document/record) including `ingest_validate` → `assetize` → parse/normalize → govern → index run end to end.
- MinerU called with auto-selected `model_version`, OCR auto-enabled for image/pdf/tiff, images stored alongside JSON result.
- `normalized_asset_ref` includes governance, quality, lineage, source_type, content_type, title, language fields.
- `governance_result` target is `normalized_asset_ref`; `knowledge_chunk.normalized_ref_id` links to normalized ref.
- No enterprise IAM dependency. No NEXUS `llm-gateway` service.
- AI suggestions traceable to LiteLLM alias, Prompt profile version, input summary, evidence refs.
- Current version and normalized ref are derived read models.
- Job failures locatable and retryable. Permission leakage rate = 0.
- P0 deployment does not require RabbitMQ or Redis.
- Imported data sources default L1/L2 unless explicit L3/L4 exception evidence and audit.
- Each simplified capability has a documented upgrade trigger and migration path.
