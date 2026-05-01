# NEXUS

NEXUS is an enterprise data and knowledge asset platform. It is currently defined by v2.2 architecture, product Spec, and Prototype documents under `docs/`.

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
├── ARCHTECT.md     # Concise architecture contract, v2.2
├── SPEC.md         # Concise product/spec contract, v2.2
├── readme.md       # Project overview
├── docs/           # Full source design documents
├── nexus-api/      # API/control-plane implementation area
├── nexus-app/      # Application/shared implementation area
└── nexus-console/  # Console/frontend implementation area
```

## Source Documents

- `docs/企业数据与知识资产平台技术选型和架构nexus_v2.2.md`
- `docs/企业数据与知识资产平台需求Spec_v2.2.md`
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`

Root documents are distilled implementation contracts:

- `ARCHTECT.md`: architecture boundaries, modules, data model, state model, AI governance, rules, tech baseline.
- `SPEC.md`: roles, scope, product flows, APIs, non-functional requirements, acceptance criteria.
- `CLAUDE.md`: Claude agent instructions.
- `AGENTS.md`: Codex agent instructions.

## Critical Architecture Decisions

- NEXUS does not depend on enterprise IAM. It uses local `identity-org-service`; DingTalk sync is optional.
- NEXUS does not develop `llm-gateway`. Existing LiteLLM is the AI gateway platform.
- Prompt templates, Prompt versions, output schema, scoring weights, redaction policy, and governance audit data are maintained in NEXUS through `ai_prompt_profile`.
- AI governance is implemented as `metadata-service.ai-governance`, not an independent service.
- Governance starts from `normalized_document` or `normalized_record`, not raw objects or MinerU raw output.
- `document_asset.current_version_id`, `document_version.normalized_ref_id`, and quality-report reverse pointers must not be introduced.
- AI output must be structured, schema-valid, evidence-backed, confidence-scored, rule-guarded, and auditable before official adoption.

## Core P0 Capabilities

- Local organization, user, role, API caller, and API key management.
- Data source registration and file/NAS/crawler ingestion.
- Raw object and original JSON package retention.
- Persistent job center with stage, failure reason, retry, reprocess, and re-governance.
- MinerU parsing and standardization into `normalized_document` / `normalized_record`.
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
- Async jobs: RabbitMQ, Celery.
- Storage: PostgreSQL 15+, MinIO, Redis.
- Parsing: MinerU.
- AI gateway: existing LiteLLM.
- Search/index: RAGFlow, with Elasticsearch/vector engine managed by RAGFlow.
- Embedding/rerank: `bge-large-zh-v1.5`, `bge-reranker-large`.

## Implementation Guidance

Read in this order before building or changing behavior:

1. `AGENTS.md` or `CLAUDE.md`, depending on the coding agent.
2. `ARCHTECT.md` for architecture and data model constraints.
3. `SPEC.md` for product behavior, APIs, NFRs, and acceptance criteria.
4. The full `docs/` v2.2 files for details and page-level Prototype behavior.

Any implementation that changes architecture, data model, API, UI behavior, or acceptance criteria should update the root contract documents and the relevant full design document.
