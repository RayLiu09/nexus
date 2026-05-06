# NEXUS Architecture Contract v2.3

This document is a concise architecture baseline for implementation. It is distilled from `docs/企业数据与知识资产平台技术选型和架构nexus_v2.3.md`.

## Architecture Goal

NEXUS is an enterprise data and knowledge asset platform for D1-D4 pilot domains. It provides controlled ingestion, raw retention, parsing, standardization, AI-led metadata governance, rule guardrails, quality scoring, RAGFlow indexing, permission-filtered search/QA, audit, and API exposure.

The P0 architecture optimizes for private deployment, local identity control, traceability, reduced manual review, replaceable external engines, and **minimum infrastructure footprint for small-to-medium data asset scale**.

## v2.3 Key Changes From v2.2

| Change | v2.2 | v2.3 |
|--------|------|------|
| Quality report entity | Standalone `quality_report` table | Embedded as `governance_result.quality_summary` (JSONB) |
| Decision log entity | Standalone `governance_decision_log` table | Embedded as `governance_result.decision_trail` (JSONB) |
| AI Prompt lifecycle | `draft → validate → publish → active → disable → archive` | Save-to-activate: new version = immediate active, old = archived |
| Rule set lifecycle | `draft → active → disabled → archived` with explicit publish | Save-to-activate: `active / disabled` only |
| Conflict resolution | Configurable enum per rule set | Fixed policy: priority-first + high-sensitivity-wins for level |
| Async job infra | RabbitMQ + Celery (required) | PostgreSQL job table + Worker poller (P0 default); MQ as scale-up path |
| Cache | Redis (required) | In-process TTL cache (P0 default); Redis as scale-up path |
| Permission model | RBAC + ABAC + org scope + level + masking | RBAC + org scope (P0); ABAC as extension point |

## System Boundaries

| Component | Responsibility | Explicitly Not Responsible For |
|-----------|----------------|--------------------------------|
| NEXUS | Asset master data, versions, governance, rules, jobs, permissions, audit, console, APIs | OCR/layout internals, vector engine internals, enterprise-wide IAM |
| `identity-org-service` | Local org units, users, roles, API callers, org scopes | Enterprise IAM or company-wide identity governance |
| DingTalk adapter | Optional department/user sync into local identity model | Runtime dependency or permission decision authority |
| MinerU | PDF/Office/image/scanned-document parsing artifacts | Asset governance, permissions, indexes |
| LiteLLM | Existing AI gateway for model routing, provider adaptation, credentials, gateway-side limits/logs | NEXUS Prompt versions, governance states, asset master data |
| `metadata-service.ai-governance` | Internal AI governance submodule, Prompt/profile management, LiteLLM calls, AI suggestions, quality scoring | Independent deployment, direct publication without rule guardrails |
| RAGFlow | Chunking, index construction, retrieval execution | NEXUS master data, permissions, audit authority |
| Crawler systems | Dynamic data source push | Governance, index governance, permissions |
| Upper systems | Consume NEXUS APIs | Direct calls to MinerU, RAGFlow, LiteLLM, or internal DBs |

## Design Principles

- Control plane and execution plane are separated.
- Raw data is persisted before processing.
- Governance happens after standardization.
- Master data is separated from execution projections.
- Derivable relations are not stored as reverse pointers.
- Automation is the default; manual review is exception handling.
- Classification, level, tags, org scope, quality admission, review triggers, and index admission are configurable rules.
- AI leads semantic understanding and scoring; rules are hard guardrails; humans handle exceptions, samples, and feedback.
- AI output must be explainable, structured, schema-valid, evidence-backed, and auditable.
- Models are replaceable through LiteLLM aliases and NEXUS-owned output schemas.
- Local identity is the baseline; DingTalk sync is optional.
- P0 reserves operations extension points but does not productize an operations center.
- **Right-size by scale: use minimum viable infrastructure in P0; each removed capability has a documented upgrade trigger and migration path.**

## Logical Layers

1. Source and access layer: console, API callers, crawler push, NAS/batch upload.
2. Raw persistence layer: MinIO `raw/`, `staging/`, `parsed/`, `normalized/`; PostgreSQL ledgers and checksums.
3. Job and processing layer: `job-orchestrator`, PostgreSQL job queue + Worker (P0) / RabbitMQ + Celery (scale-up), parse workers, `normalize-service`.
4. Standardization and governance layer: `normalized_document`, `normalized_record`, `metadata-service.ai-governance`, `metadata-enrich`, `governance-rule`.
5. Master data layer: `metadata-service` for assets, versions, governance results (with embedded quality summary and decision trail), read models.
6. Index, permission, and service layer: `ragflow-adapter`, RAGFlow, `search-service`, `iam-audit-service`, `nexus-api`.

## Core Modules

| Module | P0 Role |
|--------|---------|
| `nexus-api` | External API for assets, search, QA, jobs, governance, rules, AI Prompt profiles, auth verification |
| `nexus-console` | Admin and governance console |
| `identity-org-service` | Local org/user/API caller master data |
| `ingest-gateway` | Upload, batch import, access auth, idempotency |
| `source-adapters` | NAS, crawler, DB, webhook adapters |
| `raw-storage` | Object write and lifecycle management |
| `metadata-service` | Asset, version, classification, level, tags, org scope, index status master data |
| `metadata-service.ai-governance` | Prompt configs, AI suggestions, AI quality scoring, evidence, confidence |
| `governance-rule` | Configurable rule sets, rule execution, fixed conflict resolution |
| `job-orchestrator` | Job state machine, retries, compensation, callbacks |
| `parse-workers` | MinerU parsing execution |
| `normalize-service` | `normalized_document` and `normalized_record` generation |
| `metadata-enrich` | Governance context assembly and sensitivity recognition |
| `ragflow-adapter` | RAGFlow dataset, chunk profile, index sync, status callback |
| `search-service` | Permission-filtered hybrid retrieval, rerank, QA context |
| `iam-audit-service` | RBAC, org scope filtering, audit (ABAC as extension point) |

## Master Data Contract

Required P0 objects:

`org_unit`, `user_account`, `api_caller`, `data_source`, `ingest_batch`, `raw_object`, `document_asset`, `document_version`, `parse_artifact`, `normalized_asset_ref`, `ai_prompt_profile`, `ai_governance_run`, `governance_rule_set`, `governance_rule`, `governance_result`, `knowledge_chunk`, `index_manifest`, `job`, `audit_log`.

Removed from v2.2: `quality_report` (embedded in `governance_result.quality_summary`), `governance_decision_log` (embedded in `governance_result.decision_trail`).

Modeling constraints:

- `document_asset` is the long-lived asset identity and does not store current version.
- `document_version` is the processing, governance, and index boundary and does not store normalized reference.
- `normalized_asset_ref.version_id` is the only relation from standardization result to version.
- `governance_result` is the authoritative governance conclusion per version; it contains `quality_summary` (JSONB) and `decision_trail` (JSONB) instead of separate entities.
- Use read models such as `asset_current_version_view` and `version_current_normalized_ref_view` for current-state queries.
- Use partial unique constraints to enforce one effective/current record where needed.

## Version State Contract

Allowed `document_version.version_status` values:

| Status | Meaning | Searchable |
|--------|---------|------------|
| `processing` | Ingest, parse, standardize, govern, or index in progress | No |
| `available` | Passed automated or manual admission and can serve authorized users | Yes |
| `review_required` | Needs manual review due to quality, governance, sensitivity, permission, or index issue | No |
| `archived` | Replaced historical version | No by default |
| `disabled` | Manually disabled | No |
| `failed` | Unrecoverable processing failure | No |

Entering `available` requires:

- effective generated normalized reference;
- `governance_result.quality_summary.quality_level = pass`;
- effective governance result with required classification, level, tags, and org scope;
- no blocking rule;
- sufficient AI confidence and evidence;
- no other available version for the same asset, or old version archived in the same transaction.

## AI Governance Architecture

- NEXUS does not develop `llm-gateway`; existing LiteLLM is the AI gateway.
- NEXUS owns `ai_prompt_profile`: model alias reference, task type, Prompt template, output schema, scoring weights, temperature, max input tokens, redaction policy, auto-incrementing version. **Save-to-activate: saving creates a new version (active), old version becomes archived.**
- `metadata-service.ai-governance` renders Prompt, applies field whitelist and redaction, calls LiteLLM alias, validates structured output, records audit summary, and persists `ai_governance_run`.
- `ai_governance_run` records: version, normalized ref, Prompt profile+version, LiteLLM alias, input hash/summary, governance suggestions, quality scores, evidence refs, confidence, validation status, adoption status. Human feedback is recorded in `governance_result.decision_trail`.
- External models must not receive unmasked L3/L4 plain text unless using an approved private LiteLLM alias or an explicit security exception.

## Rule Governance Architecture

P0 uses PostgreSQL configuration tables plus a restricted JSON expression evaluator. Do not introduce a heavyweight external rule engine in P0.

Rule types: classification inference, level override, tag suggestion and restriction, org scope inference, sensitive admission, quality admission, manual review trigger, index admission.

**v2.3 lifecycle: rules are save-to-activate. Rule set `version` auto-increments on each save. No `draft` state or explicit publish step in P0.**

Conflict resolution (fixed policy, not configurable in P0):
- Level conflicts: high-sensitivity-first (L4 > L3 > L2 > L1).
- Classification and tag conflicts: highest-priority rule wins.
- Org scope conflicts: narrower scope wins; if irresolvable, enter `review_required`.

Rule execution order:

1. Build `governance_context` from normalized object, source hints, AI suggestions, sensitivity result, and org context.
2. Validate AI output schema and evidence.
3. Execute deterministic rules in priority order.
4. Resolve conflicts using fixed policy.
5. Write `governance_result` with embedded `quality_summary` and `decision_trail`.
6. Decide version status and index admission.

## Core Flows

Document ingestion:

`upload -> raw_object -> job (PG queue) -> MinerU parse -> normalized_document -> normalized_asset_ref -> AI governance (ai_governance_run) -> rules -> governance_result (quality_summary + decision_trail) -> available/review_required -> RAGFlow index`.

Structured/crawler ingestion:

`crawler/webhook/batch -> raw_object JSON -> normalized_record -> normalized_asset_ref -> AI governance -> rules -> governance_result -> index`.

Retrieval and QA:

`caller/user context -> auth verify (RBAC + org scope) -> search-service -> RAGFlow retrieval -> org scope and level check -> rerank/context -> answer with source citations -> audit`.

Reprocess and re-governance:

Rule change, Prompt update, LiteLLM alias change, parse failure, index failure, manual review, or score calibration may trigger reprocess, re-governance, AI re-score, or index rebuild. These flows must be idempotent and auditable.

## Technology Baseline

| Area | P0 Baseline | Scale-Up Path |
|------|-------------|---------------|
| API/control plane | Python 3.11, FastAPI 0.115+, Pydantic v2 | — |
| Python dependency management | uv, `pyproject.toml`, `uv.lock` | — |
| Persistence | PostgreSQL 15+, SQLAlchemy 2.x, Alembic | — |
| Object storage | MinIO | — |
| Cache | In-process TTL cache | Redis 7.x when horizontally scaling |
| Async jobs | PostgreSQL job table + Worker poller | RabbitMQ + Celery when throughput exceeds single-node capacity |
| Frontend | React 19, Next.js 16 App Router, TypeScript | — |
| Charts | ECharts 5.x | — |
| Parsing | MinerU | — |
| AI gateway | Existing LiteLLM | — |
| Search/index | RAGFlow, Elasticsearch/vector engine managed by RAGFlow | — |
| Embedding/rerank | `bge-large-zh-v1.5`, `bge-reranker-large` | — |

## Security And Audit

- P0: RBAC plus org scope filtering plus data level visibility check (L3/L4 requires explicit role grant).
- ABAC policy evaluation is an architecture extension point, not a P0 requirement.
- Cross-org access is denied by default.
- L4 content masking is implemented when L4 data actually exists in the deployment.
- API keys support scope, quota, disable, and audit.
- Rule expressions cannot execute arbitrary code.
- Logs must not expose sensitive fields, API keys, or long raw content.
- Audit must cover: access, version status change, reprocess, re-governance, Prompt config changes, rule changes, AI adoption, human override, and API key changes.

## Deployment Boundary

P0 required infrastructure: PostgreSQL, MinIO, RAGFlow, MinerU, LiteLLM (existing platform). Redis and RabbitMQ are optional scale-up components.

Single-node deployment may co-locate control, processing, and search adapters for pilot use. Three-node deployment separates control/metadata, parsing/standardization, and retrieval/indexing. LiteLLM remains an existing external platform and is not part of NEXUS node deployment.

## Scale-Up Triggers

Each capability simplified in v2.3 has a documented upgrade trigger:

| Simplified Capability | Upgrade Trigger |
|-----------------------|-----------------|
| `quality_report` as embedded JSONB | Need independent quality history queries, compliance audit, or quality workflow |
| `governance_decision_log` as embedded JSONB | Need per-rule hit rate analysis, AI acceptance rate stats, or compliance audit |
| `ai_prompt_profile` save-to-activate | Multi-person Prompt review, approval workflow, or gray release needed |
| Rule save-to-activate | Rule change approval flow, time-window rollback, or gray release needed |
| PostgreSQL job queue | Single-node queue becomes throughput bottleneck (typically >500 concurrent parse jobs) |
| In-process cache | Horizontal scaling, distributed cache invalidation, or distributed locks needed |
| ABAC extension point | Cross-org sharing, temporary approval, or attribute-based dynamic permissions needed |

## P0 Architecture Acceptance

- Ingestion, parsing, standardization, AI governance, rule guardrails, index, search, QA, permission, and audit can run end to end.
- No enterprise IAM dependency is required.
- No NEXUS `llm-gateway` service exists.
- AI suggestions and quality scores are traceable to LiteLLM alias, Prompt profile version, input summary, and evidence refs in `ai_governance_run`.
- Governance decision trail and quality summary are accessible via `governance_result`.
- Current version and current normalized reference are derived read models.
- Job failure can be located and retried.
- Permission leakage rate is zero.
- P0 deployment does not require RabbitMQ or Redis.
- Each simplified capability has a documented upgrade trigger and migration path.
