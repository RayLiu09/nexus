# AGENTS.md

This is the Codex coding-agent contract for NEXUS. It applies to the whole repository unless a deeper `AGENTS.md` overrides it.

## Read First

- `readme.md`: project overview and repository map.
- `ARCHTECT.md`: architecture contract distilled from `docs/企业数据与知识资产平台技术选型和架构nexus_v2.4.md`.
- `SPEC.md`: product and requirement contract distilled from `docs/企业数据与知识资产平台需求Spec_v2.2.md`.
- `WORKFLOWS.md`: human and AI Agent collaboration workflow, task package rules, parallel-agent division, quality gates, and Review Gates.
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`: page-level UI and interaction baseline.

## Mandatory Boundaries

- No enterprise IAM dependency. Use local `identity-org-service`; DingTalk org sync is optional.
- No self-developed `llm-gateway`. Use existing LiteLLM for model routing, provider adaptation, credentials, and gateway-side limits.
- Prompt management belongs to NEXUS through `ai_prompt_profile`.
- AI governance is `metadata-service.ai-governance`, not an independent service.
- Governance input must be `normalized_document` or `normalized_record`.
- Never persist redundant reverse pointers: no `document_asset.current_version_id`, no `document_version.normalized_ref_id`, no quality-report reverse pointer on version.
- AI suggestions must pass schema validation, field whitelist, redaction policy, rule guardrails, confidence thresholds, and state-machine decisions before they affect official governance results.
- P0 does not include a productized operations center, release management, monitoring, alerting, or capacity planning. Only health checks, structured logs, trace IDs, job status, and basic runtime state are required.
- P0 async jobs use PostgreSQL job table + background Worker polling. Do not make RabbitMQ or Celery required unless the v2.4 scale-up trigger is explicitly approved.
- Unless explicitly configured by source approval, governance rules, manual review, or security exception, imported data sources default to L1/L2. L3/L4 are exception levels and must be auditable.

## Domain And State Rules

- Core status values: `processing`, `available`, `review_required`, `archived`, `disabled`, `failed`.
- A single asset can have at most one `available` version at a time.
- Current version and current normalized reference are read models derived from constraints and relation tables.
- `available` requires effective normalized reference, acceptable `governance_result.quality_summary`, effective governance result, no blocking rule, sufficient AI confidence, and uniqueness of the available version.
- `review_required` is only for low confidence, rule conflicts, high sensitivity, unclear org scope, quality/index admission failure, policy block, or explicit manual-review rules.
- L3/L4 review, masking, and explicit authorization are triggered only by high-sensitivity exceptions or detected sensitive content; do not treat imported data sources as L3/L4 by default.

## Implementation Expectations

- Keep API paths aligned with `/v1` from `SPEC.md`.
- Use restricted rule expressions only. Do not add arbitrary code execution for governance rules.
- Store sensitive data safely. Do not log API keys, L3/L4 plain text, or large raw content.
- Every mutation of Prompt config, rules, version status, governance result, permission, API key, AI adoption, or human override must be auditable.
- Preserve idempotency for ingest, job retry, reprocess, re-governance, AI re-score, and index rebuild flows.
- For frontend work, follow Prototype v2.2 page names and flows, especially `NX-13 AI Prompt 配置`. Do not add a NEXUS AI gateway management page.
- If changing architecture, data model, API, UI, or acceptance criteria, update `ARCHTECT.md`, `SPEC.md`, and `readme.md` as needed.

## Preferred Stack

- Backend/control plane: Python 3.11, FastAPI 0.115+, Pydantic v2, SQLAlchemy 2.x, Alembic.
- Python dependency management: uv with `pyproject.toml` and `uv.lock`.
- Frontend console: React 19, Next.js 16 App Router, TypeScript, ECharts for basic charts.
- Async jobs: PostgreSQL job table + Worker poller, row-level claim locking, lock lease/heartbeat, retry/backoff, dead-letter state. RabbitMQ + Celery are scale-up components only.
- Storage/search: PostgreSQL 15+, MinIO, in-process TTL cache for P0, RAGFlow, Elasticsearch/vector engine managed by RAGFlow. Redis 7.x is a scale-up component only.
- Parsing and AI: MinerU, LiteLLM, OpenAI-compatible/private models, `bge-large-zh-v1.5`, `bge-reranker-large`.

## Working Practice

- Use `rg` for repository search.
- Follow `WORKFLOWS.md` for non-trivial work: define a bounded task package, honor forbidden changes, produce tests or verification evidence, and pass the relevant Review Gate.
- Start each weekly implementation cycle by reading the matching `docs/task-packages/wk_<week>_task_package.md`. If the work is not covered there, update or create a bounded task package first.
- Use contract-first parallelism. Freeze API schemas, state enums, UI state semantics, and file ownership before concurrent Agent work.
- If multiple AI Agents work in parallel in a task cycle, create the `WORKFLOWS.md` parallel-agent contract before implementation. This rule applies only to parallel multi-Agent scenarios.
- Keep task packages small, ideally 0.5 to 1.5 days of scoped work. Avoid large cross-cutting patches unless explicitly requested.
- Keep externally consumed business APIs in `nexus-api`. `nexus-console` control-plane APIs are internal to the admin console by principle and must not be exposed as business-facing APIs for external callers.
- Avoid broad rewrites unless the user asks for a version upgrade.
- Do not silently change the v2.4 contract to simplify implementation.
- Add or update tests for state transitions, permission filtering, governance rules, AI output validation, Prompt versioning, and audit trails.
- High-risk changes to data model, AI governance, rule engine, permissions/audit, version state, RAGFlow integration, API contract, or P0 UX require the corresponding `WORKFLOWS.md` Review Gate before they can be considered complete.
