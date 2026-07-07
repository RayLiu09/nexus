# CLAUDE.md

This file is the Claude coding-agent contract for NEXUS. It is distilled from the v3.0 architecture and v8.0 platform documents. Keep it short in day-to-day use, but do not bypass these constraints.

## Source Of Truth

- Architecture baseline: `ARCHITECT.md`, derived from `docs/企业数据与知识资产平台技术选型和架构nexus_v3.0.md`.
- Product baseline: `SPEC.md`, derived from `docs/企业数据与知识资产平台需求Spec_v2.2.md` and `docs/企业数据与知识资产平台nexus_v8.0.md`.
- Workflow baseline: `WORKFLOWS.md`, derived from `docs/基于AI Agent的开发计划v1.0.md`.
- UI baseline: `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`.
- If a local implementation conflicts with these documents, treat the documents as the contract unless the user explicitly changes the product direction.

## Project Mission

NEXUS is an enterprise data and knowledge asset platform. It unifies ingestion, raw retention, parsing, standardization, AI-led governance, rule guardrails, quality scoring, adapter-based semantic retrieval indexing, permission-filtered search, QA, audit, and API service exposure for D1-D4 pilot data domains.

P0 is the smallest usable loop: data source → raw object → ingest_validate → assetize → parse/normalize → normalized_asset_ref → AI governance and quality score → rules → available or review_required → semantic retrieval index → permission-filtered search / QA → traceable source citation.

## Non-Negotiable Architecture Rules

- Do not add an enterprise IAM dependency. NEXUS uses local `identity-org-service`; DingTalk org sync is optional and non-blocking.
- Do not build `llm-gateway`. AI model routing, provider adaptation, credentials, and gateway-side limits belong to the existing LiteLLM platform.
- Do keep Prompt maintenance in NEXUS. Prompt templates, Prompt versions, output schema, scoring weights, redaction policy, and governance audit data are managed by `ai_prompt_profile`.
- Do not create an independent `ai-governance-orchestrator` service. AI governance is `metadata-service.ai-governance`.
- Do not add `asset.current_version_id`, `asset_version.normalized_ref_id`, or any reverse pointer between versions and governance entities. Use single-direction relations and read models.
- Do not create standalone `quality_report` or `governance_decision_log` entities. These are embedded JSONB fields in `governance_result` (`quality_summary` and `decision_trail`). Only extract them when the documented upgrade trigger is met.
- **Governance input must be `normalized_document` or `normalized_record` (accessed via `normalized_asset_ref`), never raw files, raw crawler JSON, or MinerU raw output.**
- **`governance_result` target is `normalized_asset_ref`, not `asset_version`. `knowledge_chunk.normalized_ref_id` links chunk to normalized ref.**
- AI output never becomes official governance state directly. It must pass schema validation, field whitelist checks, redaction policy, rule guardrails, confidence thresholds, and state-machine decisions.
- Operations features are reserved architecture extension points. P0 only requires health checks, structured logs, trace IDs, job status, and basic runtime state.
- Do not introduce RabbitMQ, Celery, or Redis as P0 required dependencies. Use PostgreSQL job table + Worker poller and in-process TTL cache until the scale-up triggers documented in `ARCHITECT.md` are met.
- P0 permission model is RBAC + org scope filtering. Do not implement full ABAC policy evaluation until the extension trigger is met.
- P0 imported data sources default to L1/L2. Do not default a source to L3/L4 unless there is explicit source approval, governance rule evidence, manual/security review, and audit.
- Single-node P0 Worker capacity is bounded: 8-12 recommended active pipeline jobs, 16 maximum; MinerU parse jobs 2-4 concurrent.
- **assetize** (create asset/asset_version anchor) and **normalize** (content standardization) are distinct stages with distinct owners. Do not conflate them.
- **normalize-service uses LLM semantic extraction + rule-engine fallback validation. Rules are defined by domain experts, not hard-coded.**
- **MinerU is called with auto-selected `model_version` (HTML→MinerU-HTML, default→pipeline, complex→vlm) and auto-enabled OCR for image/pdf/tiff. Images must be stored at `parsed/<version_id>/<artifact_id>/images/` alongside the JSON result.**
- **Knowledge Pipeline is independent of Asset Pipeline.** They connect only through `normalized_asset_ref`. P0 Knowledge Pipeline scope = Pipeline 1 (semantic retrieval KB) only.
- **`metadata_enrich` tag generation targets normalized assets, not chunks.** High-confidence tags auto-commit (with audit log); low-confidence tags enter human review queue.

## Core Domain Objects

- Identity: `org_unit`, `user_account`, `api_caller`.
- Ingestion: `data_source`, `ingest_batch`, `raw_object`.
- Asset master data: `asset` (renamed from `document_asset`), `asset_version` (renamed from `document_version`).
- Parsing (Pipeline A only): `parse_artifact`.
- Standardization: `normalized_asset_ref` (with full governance/quality/lineage/source_type/content_type/title/language fields), `normalized_document`, `normalized_record`.
- AI governance: `ai_prompt_profile`, `ai_governance_run`.
- Governance rules (file-based): `config/governance_rules.json` — the single source of truth for business rules (classifications, levels, tags, quality scoring, knowledge types), maintained by business experts via console, protected by schema validation + ETag optimistic lock + fcntl write lock.
- Governance result: `governance_result` (includes embedded `quality_summary` and `decision_trail`; records `rules_schema_version` + `rules_content_hash` as snapshot evidence).
- Knowledge and index: `knowledge_chunk` (with `normalized_ref_id`), `index_manifest`.
- Jobs and audit: `job`, `job_stage`, `audit_log`.

## Pipeline Stages

Both pipelines share: `ingest_validate` → `assetize` → (parse — Pipeline A only) → `normalize`.

Pipeline A (document): `ingest_validate` → `assetize` → **parse** (MinerU + image extraction) → **normalize** → `normalized_asset_ref(type=document)`.

Pipeline B (record): `ingest_validate` → `assetize` → **normalize** (no MinerU) → `normalized_asset_ref(type=record)`.

Routing determined at job creation from `DataSource.source_type` + `raw_object.mime_type`, stored in `Job.payload.pipeline_type`. Workers read from payload; no runtime inference.

Required audit events for both pipelines: `INGEST_BATCH_SUBMITTED`, `RAW_OBJECT_PERSISTED`, `INGEST_VALIDATE_COMPLETED`, `VERSION_STATUS_CHANGED`, `PIPELINE_FAILED`.

## State Contract

Allowed asset-version statuses:

- `processing`: ingest, parse, standardize, govern, or index in progress.
- `available`: usable by authorized users and eligible for index.
- `review_required`: blocked by quality, governance, sensitivity, permission, confidence, or index admission issues.
- `archived`: historical version replaced by a newer available version.
- `disabled`: manually disabled.
- `failed`: unrecoverable processing failure.

Only one `available` version may exist for the same asset at a time. Current version is a read model, not a stored pointer.

## AI Governance Contract

- LiteLLM is external. Store only model alias references and NEXUS-side audit summaries.
- `ai_prompt_profile` is P0. Saving creates a new version (auto-incremented) and immediately sets it as `active`; the old version becomes `archived`. No `draft` state.
- Any Prompt template, model alias reference, schema, scoring weight, or redaction change must create a new version and write an audit log entry.
- L3/L4 plain text must not be sent to external models unless the LiteLLM alias is approved as a private model or security policy explicitly allows it.
- Persist AI suggestions, quality scores, evidence refs, confidence, validation status, and adoption status in `ai_governance_run`. Human feedback and override details go in `governance_result.decision_trail`.

## API And UI Contract

- Public API baseline uses `/v1`.
- P0 API groups: identity, data sources, ingest, raw objects (incl. presigned download-url), jobs, assets, normalized refs (incl. chunk list), knowledge chunks, search, QA, governance rules, governance results, AI Prompt profiles, AI governance runs, auth verification.
- P0 console pages: workbench, data source management, data ingestion, raw object ledger, job center, asset catalog, asset detail, governance center, rule config, permission and audit, AI Prompt config.
- P1 console pages: retrieval test, knowledge assets, optional DingTalk sync, API Key operation enhancements, reporting.
- `nexus-console` control-plane APIs are internal to the admin console and must not be exposed as business-facing APIs. Business-facing APIs belong in `nexus-api`.

## Implementation Guardrails

- Use Python + FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic for API/control-plane work.
- Use `uv` for Python dependency management. Prefer `pyproject.toml` and `uv.lock`.
- Use React + Next.js + TypeScript for console work.
- Use PostgreSQL for master data and P0 job queue, MinIO for object storage, MinerU for parsing, and adapter-based semantic retrieval for index/search execution. The concrete semantic retrieval backend is selected outside the domain model; RAGFlow is no longer the platform semantic retrieval baseline. The P0 job queue must use row-level claim locking, lock lease/heartbeat, retry/backoff, and dead-letter states.
- Business governance rules (classifications, levels, tags, quality scoring, knowledge types) are stored exclusively in `config/governance_rules.json`. This file is the single source of truth for AI governance decisions. Console edits must pass Pydantic schema validation, ETag optimistic locking (to prevent lost updates), and fcntl exclusive file lock (to guarantee atomic writes). Never execute arbitrary user-supplied code or expressions.
- All mutating API and job operations need idempotency strategy, audit events, and trace IDs.
- Logs must not contain sensitive fields, API keys, raw L3/L4 content, or large document bodies.
- Any code that changes governance, permission, Prompt, rule, version status, API key, or AI adoption state must write audit logs.
- Non-trivial AI Agent work must follow `WORKFLOWS.md`: bounded task package, explicit forbidden changes, deliverables, tests or verification, and Review Gate where required.
- Parallel AI Agent work must be contract-first. Freeze API schemas, state enums, UI state semantics, and ownership before concurrent backend/frontend/test/doc changes.
- Weekly implementation must start by reading the corresponding `docs/task-packages/wk_<week>_task_package.md`; do not begin coding from memory or broad docs alone.

## When Editing

- Read the relevant root contract first: `ARCHITECT.md` for architecture, `SPEC.md` for product behavior, `WORKFLOWS.md` for AI Agent collaboration and Review Gates, and the Prototype doc for UI behavior.
- For weekly execution, read the matching task package in `docs/task-packages/` before making changes.
- Preserve v3.0 boundaries unless the user explicitly requests a new version.
- Update root contracts when implementation changes alter architecture, data model, API, UI, or acceptance criteria.
- Prefer explicit tests for state transitions, idempotency, permission filtering, rule evaluation, AI output validation, and audit generation.
- Do not merge or present high-risk changes as complete until the applicable `WORKFLOWS.md` Review Gate has been satisfied.
