# CLAUDE.md

This file is the Claude coding-agent contract for NEXUS. It is distilled from the v2.4 architecture, Spec, and Prototype documents. Keep it short in day-to-day use, but do not bypass these constraints.

## Source Of Truth

- Architecture baseline: `ARCHTECT.md`, derived from `docs/企业数据与知识资产平台技术选型和架构nexus_v2.4.md`.
- Product baseline: `SPEC.md`, derived from `docs/企业数据与知识资产平台需求Spec_v2.2.md`.
- Workflow baseline: `WORKFLOWS.md`, derived from `docs/基于AI Agent的开发计划v1.0.md`.
- UI baseline: `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`.
- If a local implementation conflicts with these documents, treat the documents as the contract unless the user explicitly changes the product direction.

## Project Mission

NEXUS is an enterprise data and knowledge asset platform. It unifies ingestion, raw retention, parsing, standardization, AI-led governance, rule guardrails, quality scoring, RAGFlow indexing, permission-filtered search, QA, audit, and API service exposure for D1-D4 pilot data domains.

P0 is the smallest usable loop: data source -> raw object -> job -> parse -> normalized asset ref -> AI governance and quality score -> rules -> available or review_required -> index -> permission-filtered search / QA -> traceable source citation.

## Non-Negotiable Architecture Rules

- Do not add an enterprise IAM dependency. NEXUS uses local `identity-org-service`; DingTalk org sync is optional and non-blocking.
- Do not build `llm-gateway`. AI model routing, provider adaptation, credentials, and gateway-side limits belong to the existing LiteLLM platform.
- Do keep Prompt maintenance in NEXUS. Prompt templates, Prompt versions, output schema, scoring weights, redaction policy, and governance audit data are managed by `ai_prompt_profile`.
- Do not create an independent `ai-governance-orchestrator` service. AI governance is `metadata-service.ai-governance`.
- Do not add `document_asset.current_version_id`, `document_version.normalized_ref_id`, or any reverse pointer between versions and governance entities. Use single-direction relations and read models.
- Do not create standalone `quality_report` or `governance_decision_log` entities. In v2.4 these are embedded JSONB fields in `governance_result` (`quality_summary` and `decision_trail`). Only extract them as independent entities when the documented upgrade trigger is met.
- Governance input must be `normalized_document` or `normalized_record`, never raw files, raw crawler JSON, or MinerU raw output.
- AI output never becomes official governance state directly. It must pass schema validation, field whitelist checks, redaction policy, rule guardrails, confidence thresholds, and state-machine decisions.
- Operations features such as release management, monitoring, alerting, and capacity planning are reserved architecture extension points. P0 only requires health checks, structured logs, trace IDs, job status, and basic runtime state.
- Do not introduce RabbitMQ, Celery, or Redis as P0 required dependencies. Use PostgreSQL job table + Worker poller and in-process TTL cache until the scale-up triggers documented in `ARCHTECT.md` are met.
- P0 permission model is RBAC + org scope filtering. Do not implement full ABAC policy evaluation until the extension trigger is met.
- P0 imported data sources default to L1/L2. Do not default a source to L3/L4 unless there is explicit source approval, governance rule evidence, manual/security review, and audit.
- Single-node P0 Worker capacity is bounded: 8-12 recommended active pipeline jobs, 16 maximum; MinerU parse jobs should stay at 2-4 concurrent.

## Core Domain Objects

- Identity: `org_unit`, `user_account`, `api_caller`.
- Ingestion: `data_source`, `ingest_batch`, `raw_object`.
- Asset master data: `document_asset`, `document_version`.
- Standardization: `normalized_asset_ref`, `normalized_document`, `normalized_record`.
- AI governance: `ai_prompt_profile`, `ai_governance_run`.
- Rules and governance result: `governance_rule_set`, `governance_rule`, `governance_result` (includes embedded `quality_summary` and `decision_trail`).
- Knowledge and index: `knowledge_chunk`, `index_manifest`.

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
- `ai_prompt_profile` is P0. Saving a config creates a new version (auto-incremented) and immediately sets it as `active`; the old version becomes `archived`. No `draft` state or explicit publish step in v2.4.
- Any Prompt template, model alias reference, schema, scoring weight, or redaction change must create a new version and write an audit log entry.
- L3/L4 plain text must not be sent to external models unless the LiteLLM alias is approved as a private model or security policy explicitly allows it.
- L3/L4 handling is an exception path. Imported source defaults are L1/L2 unless explicit evidence or approval elevates the level.
- Persist AI suggestions, quality scores, evidence refs, confidence, validation status, and adoption status in `ai_governance_run`. Human feedback and override details go in `governance_result.decision_trail`.

## API And UI Contract

- Public API baseline uses `/v1`.
- P0 API groups: identity, data sources, ingest, raw objects, jobs, assets, search, QA, governance rules, governance results, AI Prompt profiles, AI governance runs, auth verification.
- P0 console pages: workbench, data source management, data ingestion, raw object ledger, job center, asset catalog, asset detail, governance center, rule config, permission and audit, AI Prompt config.
- P1 console pages: retrieval test, knowledge assets, optional DingTalk sync, API Key operation enhancements, reporting.

## Implementation Guardrails

- Use Python + FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic for API/control-plane work unless the repo later defines a stronger convention.
- Use `uv` for Python dependency management. Prefer `pyproject.toml` and `uv.lock`; use uv workflows for adding, removing, syncing, and locking Python packages.
- Use React + Next.js + TypeScript for console work.
- Use PostgreSQL for master data and P0 job queue, MinIO for object storage, MinerU for parsing, RAGFlow for chunking/index/search execution. The P0 job queue must use row-level claim locking, lock lease/heartbeat, retry/backoff, and dead-letter states. Redis and RabbitMQ+Celery are optional scale-up components; do not require them in P0.
- Rules should be table-driven with a restricted JSON expression or JSONLogic-style subset. Never execute arbitrary user-supplied code.
- All mutating API and job operations need idempotency strategy, audit events, and trace IDs.
- Logs must not contain sensitive fields, API keys, raw L3/L4 content, or large document bodies.
- Any code that changes governance, permission, Prompt, rule, version status, API key, or AI adoption state must write audit logs.
- Non-trivial AI Agent work must follow `WORKFLOWS.md`: bounded task package, explicit forbidden changes, deliverables, tests or verification, and Review Gate where required.
- Parallel AI Agent work must be contract-first. Freeze API schemas, state enums, UI state semantics, and ownership before concurrent backend/frontend/test/doc changes.
- When multiple AI Agents work in parallel in the same task cycle, create the parallel-agent contract described in `WORKFLOWS.md` before implementation. This requirement applies only to parallel multi-Agent scenarios.
- Weekly implementation must start by reading the corresponding `docs/task-packages/wk_<week>_task_package.md`; do not begin coding from memory or broad docs alone.
- `nexus-console` control-plane APIs are internal to the admin console by principle and must not be exposed as business-facing APIs for external callers; business-facing APIs belong in `nexus-api`.

## When Editing

- Read the relevant root contract first: `ARCHTECT.md` for architecture, `SPEC.md` for product behavior, `WORKFLOWS.md` for AI Agent collaboration and Review Gates, and the Prototype doc for UI behavior.
- For weekly execution, read the matching task package in `docs/task-packages/` before making changes.
- Preserve the v2.4 boundaries unless the user explicitly requests a new version.
- Update root contracts when implementation changes alter architecture, data model, API, UI, or acceptance criteria.
- Prefer explicit tests for state transitions, idempotency, permission filtering, rule evaluation, AI output validation, and audit generation.
- Do not merge or present high-risk changes as complete until the applicable `WORKFLOWS.md` Review Gate has been satisfied.
