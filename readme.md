# NEXUS

NEXUS is an enterprise data and knowledge asset platform. It is currently defined by the v3.0 architecture baseline and v8.0 platform documents under `docs/`.

## What NEXUS Does

NEXUS turns enterprise source data into governed, searchable, auditable data and knowledge assets:

```text
data source
  -> raw object retention
  -> parsing / standardization
  -> AI governance and quality scoring
  -> configurable rule guardrails
  -> available or review_required asset version
  -> RAGFlow indexing
  -> permission-filtered search / QA / API consumption
  -> source citation and audit
```

The current P0 target covers D1-D4 pilot domains and focuses on an end-to-end usable loop rather than a full operations center or advanced knowledge-graph/SFT production system.

## Repository Map

```text
.
├── AGENTS.md       # Codex coding-agent contract
├── CLAUDE.md       # Claude coding-agent contract
├── ARCHITECT.md     # Concise architecture contract, v3.0
├── SPEC.md         # Concise product/spec contract, v3.0
├── readme.md       # Project overview
├── docs/           # Full source design documents
├── nexus-app/      # Core backend/domain models, migrations, and services
├── nexus-api/      # Externally consumed /v1 business API service
└── nexus-console/  # Console/frontend implementation area
```

Week 1 implementation baselines:

- `docs/contracts/p0_api_state_contract.md`: frozen P0 API, status, UI label, audit event, and M1 demo path baseline.
- `docs/testing/p0_e2e_checklist.md`: P0 E2E and M1 verification checklist draft.
- `docs/samples/p0_sample_inventory.md`: D1-D4 sample inventory and permission sample placeholders.
- `docs/review/wk1_review_evidence.md`: Week 1 Review Gate evidence.
- `nexus-app/`: Week 1 core settings, database setup, master data models, Alembic migration, domain schemas, application services, environment checker, and pytest baseline.
- `nexus-api/`: FastAPI `/v1` externally consumed business API skeleton, route adaptation to `nexus-app`, response envelopes, trace/log/error handling, and pytest baseline.
- `nexus-console/`: Next.js App Router skeleton and P0 route placeholders.

Week 2 implementation baselines:

- `docs/week2_runbook.md`: M1 ingest-to-assetization runbook.
- `docs/review/wk2_review_evidence.md`: Week 2 Review Gate evidence.
- `nexus-app/`: M1 pipeline services, MinIO/S3 storage adapter, MinerU adapter boundary, job/stage, parse artifact, normalized ref, asset/version models, Alembic migration, and tests.
- `nexus-api/`: `/v1` ingest submit, job, parse artifact, normalized ref, asset, and version route adaptation to `nexus-app`.
- `nexus-console/`: M1 live `/v1` API views for workbench, ingest, raw ledger, jobs, asset catalog, asset detail, and audit basics.

Architecture v3.0 baseline:

- P0 async jobs use PostgreSQL job table + background Worker polling with row-level claim locking, lock lease/heartbeat, retry/backoff, dead-letter state, and idempotent job creation.
- Single-node P0 capacity is intentionally bounded: 8-12 recommended active pipeline jobs, 16 maximum; MinerU parse jobs should stay at 2-4 concurrent before planning MQ/multi-node scale-up.
- Imported data sources default to L1/L2. L3/L4 are explicit exception levels requiring source approval, rule evidence, manual/security review, masking controls, and audit.
- RabbitMQ, Celery, and Redis are optional scale-up components, not P0 required infrastructure.

## Source Documents

- `docs/企业数据与知识资产平台技术选型和架构nexus_v3.0.md`
- `docs/企业数据与知识资产平台nexus_v8.0.md`
- `docs/企业数据与知识资产平台需求Spec_v2.2.md`
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`

Root documents are distilled implementation contracts:

- `ARCHITECT.md`: architecture boundaries, modules, data model, state model, AI governance, rules, tech baseline.
- `SPEC.md`: roles, scope, product flows, APIs, non-functional requirements, acceptance criteria.
- `CLAUDE.md`: Claude agent instructions.
- `AGENTS.md`: Codex agent instructions.

## Critical Architecture Decisions

- NEXUS does not depend on enterprise IAM. It uses local `identity-org-service`; DingTalk sync is optional.
- NEXUS does not develop `llm-gateway`. Existing LiteLLM is the AI gateway platform.
- Prompt templates, Prompt versions, scenario, output schema, scoring weights, redaction policy, dry-run previews, and governance audit data are maintained in NEXUS through `ai_prompt_profile`.
- AI governance is implemented as `metadata-service.ai-governance`, not an independent service.
- Governance starts from `normalized_document` or `normalized_record` (via `normalized_asset_ref`), not raw objects or MinerU raw output. `governance_result` target is `normalized_asset_ref`.
- `asset.current_version_id`, `asset_version.normalized_ref_id`, and quality-report reverse pointers must not be introduced.
- AI output must be structured, schema-valid, evidence-backed, confidence-scored, rule-guarded, and auditable before official adoption.
- P0 does not require RabbitMQ, Celery, or Redis. PostgreSQL Worker polling and in-process TTL cache are the default.
- Imported data sources default to L1/L2 unless explicit high-sensitivity exception evidence exists.

## Core P0 Capabilities

- Local organization, user, role, API caller, and API key management.
- Data source registration and file/NAS/crawler ingestion, including scan-task orchestration for NAS/Webhook/record sources.
- Raw object and original JSON package retention.
- Persistent job center with stage, failure reason, retry, reprocess, and re-governance.
- MinerU parsing (auto model_version, OCR, image extraction) and standardization into `normalized_document` / `normalized_record` with full `normalized_asset_ref` fields.
- Pipeline B structured record assets, including job demand, occupational ability analysis, and professional major-distribution tables with domain read models.
- AI-led classification, level, tag, org-scope suggestions, and quality scoring.
- Configurable governance rules and decision tracking.
- RAGFlow chunking, indexing, and retrieval integration.
- Permission-filtered search and QA with source citations.
- Audit logs for access, governance, rules, Prompt changes, permissions, API keys, and AI adoption.

## Main Roles

- `平台/数据管理员`: platform operation, data governance, rules, Prompt config, permissions, audit.
- `业务专家`: rule review, AI suggestion review, quality calibration, search testing.
- `运维人员`: basic troubleshooting through workbench, job center, audit logs, and approved retries.
- `API 调用方`: upper systems and authorized business access through APIs.

## Baseline Stack

- Backend/control plane: Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic.
- Python dependency management: uv with `pyproject.toml` and `uv.lock`.
- Frontend console: React 19, Next.js 16 App Router, TypeScript.
- Async jobs: PostgreSQL job table + Worker poller; RabbitMQ + Celery are scale-up components.
- Storage: PostgreSQL 15+, MinIO; Redis is an optional scale-up cache.
- Parsing: MinerU.
- AI gateway: existing LiteLLM.
- Search/index: RAGFlow, with Elasticsearch/vector engine managed by RAGFlow.
- Embedding/rerank: `bge-large-zh-v1.5`, `bge-reranker-large`.

## Implementation Guidance

Read in this order before building or changing behavior:

1. `AGENTS.md` or `CLAUDE.md`, depending on the coding agent.
2. `ARCHITECT.md` for architecture and data model constraints.
3. `SPEC.md` for product behavior, APIs, NFRs, and acceptance criteria.
4. The full `docs/` architecture v3.0 / v8.0 and product/prototype v2.2 files for details and page-level Prototype behavior.

Any implementation that changes architecture, data model, API, UI behavior, or acceptance criteria should update the root contract documents and the relevant full design document.
