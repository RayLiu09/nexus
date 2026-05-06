# NEXUS Product Spec Contract v2.4

This document is the concise product and requirement contract for implementation. It is distilled from `docs/企业数据与知识资产平台需求Spec_v2.2.md` and constrained by the v2.4 architecture baseline in `ARCHTECT.md`.

## Product Goal

NEXUS一期 builds the minimum usable loop for enterprise data assets and knowledge assets:

`data ingestion -> raw retention -> parsing -> standardization -> AI governance and quality scoring -> rule guardrails -> available/review_required -> indexing -> permission-filtered search/QA -> traceable citation and audit`.

The platform focuses on D1-D4 pilot domains and does not productize D5/D6, knowledge graph production, SFT corpus production, evaluation standard library, or an operations center in P0.

## Roles

| Role | Scope |
|------|-------|
| 平台/数据管理员 | Local identity/org, data sources, ingestion, jobs, rules, AI Prompt configs, governance review, permissions, audit |
| 业务专家 | Rule review, AI suggestion review, quality calibration, search testing, knowledge asset review |
| 运维人员 | Basic job/runtime troubleshooting, retry where authorized, failure summaries |
| API 调用方 | Upper systems, smart apps, integrations, and authorized business access through API keys and user context |

Role constraints:

- Former platform admin and data admin are merged into `平台/数据管理员`.
- Former ordinary business user is merged into `API 调用方` for authorized business access.
- No enterprise IAM/SSO is required. Local identity is mandatory; DingTalk sync is optional.

## P0 Scope

- Local org/user/API caller management.
- Data source registration and file/NAS/crawler ingestion.
- Raw object retention and ingest ledger.
- Persistent job center backed by PostgreSQL job table + Worker polling, state machine, failure lookup, retry, lock lease, and dead-letter handling.
- MinerU parsing and standardization into `normalized_document` / `normalized_record`.
- AI governance and quality scoring from standardized objects.
- Configurable governance rules for classification, level, tags, org scope, quality admission, review triggers, and index admission.
- Governance decision tracking.
- RAGFlow integration for chunking, indexing, search execution.
- RBAC, org scope filtering, data-level visibility, masking for explicit L3/L4 exceptions, audit. ABAC is an extension point.
- `nexus-console` P0 pages and `/v1` P0 APIs.
- Search/QA source traceability to asset version, normalized ref, chunk, and raw object.
- Basic maintainability: health checks, structured logs, trace IDs, job status, basic runtime state.

## P1 Scope

- Optional DingTalk org sync.
- Retrieval test console.
- Basic knowledge asset management.
- API Key operation enhancements.
- Basic reports for assets, quality, search, API calls.
- Rule effect analysis.
- AI effect analysis.

## P2 Reserved

- D5/D6 production ingestion.
- Knowledge graph production.
- SFT corpus production.
- Evaluation standard library.
- Productized operations center for release, monitoring, alerting, capacity planning.
- Prompt automatic optimization, LiteLLM alias A/B comparison, active learning, batch AI re-scoring strategy.
- Full high availability upgrades.

## Console Information Architecture

P0 pages:

- 工作台: ingestion/job/review/AI adoption/rule overview/basic runtime state.
- 数据源管理: source registration, upload entry, NAS sync, crawler push config.
- 数据接入: single file, batch upload, directory import, ingestion policy.
- 原始数据台账: batch query, raw object query, checksum, replay entry.
- 作业中心: job list, stage progress, failure reason, retry, reprocess, re-governance.
- 资产目录: asset list, current version read model, versions, normalized refs, index status.
- 资产详情: overview, versions, normalized refs, AI governance, quality score, governance result, decision tracking, chunks, index manifest, lineage, audit.
- 治理中心: AI suggestions, AI quality score, AI Prompt config, review tasks, rule config, save-to-activate changes, decision tracking, quality review.
- 规则配置: rule sets, rules, validation, save-to-activate, disable, effect.
- 权限与审计: local users, roles, API keys, org scopes, approvals, audit logs.
- AI Prompt 配置: Prompt templates, LiteLLM alias references, output schema, scoring weights, redaction policies.

P1 pages:

- 检索测试.
- 知识资产.

## Key User Journeys

平台/数据管理员:

1. Maintain local org/user/API caller.
2. Configure data sources and ingestion policies.
3. Maintain AI Prompt profiles and governance rules.
4. Track jobs and failures.
5. Review `review_required` assets.
6. Configure permissions and validate retrieval.

业务专家:

1. Review AI suggestions, quality scores, and rule effects.
2. Calibrate quality score and governance outputs.
3. Test search quality and provide feedback.

API 调用方:

1. Apply for or receive API access.
2. Call assets/search/QA/jobs APIs within authorized scopes.
3. Provide caller and end-user context for permission evaluation.

运维人员:

1. Use workbench, job center, and audit logs to locate failures.
2. Retry or trigger approved recovery actions.

## Functional Requirements Summary

Identity and permission:

- Local users, org units, roles, API callers, API keys, and org scopes are mandatory.
- Calls must carry API caller context and user context where applicable.
- Permission evaluation combines RBAC, org scope, data level visibility, and masking for explicit L3/L4 exceptions. ABAC is not a P0 requirement.
- Imported data sources default to L1/L2. L3/L4 requires explicit source approval, governance rule evidence, manual/security review, and audit.

Ingestion and raw retention:

- Upload, batch, NAS, crawler, DB/webhook adapters are supported by adapter pattern.
- `idempotency_key` prevents duplicate effective assets.
- Raw objects and original JSON packages must be retained with checksum and source metadata.
- `data_source.default_level_hint` may be empty, L1, or L2; empty is treated as L2. L3/L4 must not be a normal source default.

Parsing and standardization:

- MinerU handles PDF, Office, image, scan parsing.
- Standardized output must be `normalized_document` or `normalized_record`.
- Governance cannot finalize from raw objects or MinerU raw artifacts.

AI governance and quality scoring:

- Use existing LiteLLM only; no NEXUS `llm-gateway`.
- Prompt maintenance is in NEXUS through `ai_prompt_profile`.
- `ai_prompt_profile` uses save-to-activate: create/update creates a new active version, archives the old active version, supports disable, version history, and audit. Draft/publish is an upgrade path.
- `ai_governance_run` records suggestions, quality scores, evidence refs, confidence, validation, and adoption. Human feedback and overrides are recorded in `governance_result.decision_trail`.
- AI outputs need schema validation, field whitelist checks, enum checks, redaction policy, rule guardrails, and confidence thresholds.
- Human users can revise, reject, calibrate, and submit feedback labels.

Rules and decisions:

- Rule sets use save-to-activate in P0: create/update validates restricted expressions and immediately activates the new version; disable is supported. Publish/rollback is an upgrade path.
- Rules cover classification, level, tags, org scope, quality admission, manual review triggers, and index admission.
- `governance_result.decision_trail` must record input summary, AI Prompt config, LiteLLM alias, Prompt version, AI suggestion, quality score, rule set, matched rules, candidate values, final value, confidence, adoption status, and conflict reason.

Search and QA:

- Search and QA must enforce permissions before returning content.
- Results must cite asset version, normalized ref, chunk ID, and source position.
- Unauthorized or masked content must never be returned.

Maintainability:

- Core services expose health checks.
- Structured logs and request/trace IDs are mandatory.
- Job center must show stage, failure reason, retry count, and related object.
- P0 job processing must expose enough state to identify queued/running/succeeded/failed/review/dead-lettered jobs, Worker lock ownership, retry attempts, and failure reasons.

## Public API Groups

P0 API groups include:

- Identity/org/API caller management.
- Data sources.
- Ingest submit and batch query.
- Raw object query.
- Job query, retry, reprocess.
- Asset list/detail/version/current read model.
- Search and QA.
- Governance rule sets, validation, save-to-activate updates, disable. Publish/rollback are extension APIs.
- Governance decision query.
- AI Prompt profile query/create/update save-to-activate/disable/version query. Draft/validate/publish are extension APIs.
- AI governance run query, AI re-score, AI feedback.
- Auth verification.

Use `/v1` as the external API prefix.

## Non-Functional Requirements

Performance:

- `GET /v1/assets` P95 < 200 ms.
- `GET /v1/assets/{id}` P95 < 150 ms.
- `POST /v1/search` P95 < 1 s.
- `POST /v1/qa` P95 < 5 s.
- Small-batch ingestion to searchable target < 15 minutes.
- Single-asset rule governance P95 < 3 s, excluding parse/index.
- Single-asset AI governance P95 < 30 s for small batches, excluding parse/index.

Quality:

- Standardized asset traceability: 100%.
- Governance decision traceability: 100%.
- AI governance traceability: 100%.
- AI quality score explainability: 100%.
- AI auto-adoption rate: at least 60% in integration, 75% after pilot stabilization.
- Human override feedback retention: 100%.
- Permission leakage rate: 0.
- Top-5 recall baseline: at least 60% in integration, 80% after pilot.
- QA citation rate: 100%.
- Job failure locatability: 100%.
- Key action audit coverage: 100%.

Security:

- L3/L4 exception content is masked by default.
- External models cannot receive unmasked L3/L4 plain text unless policy allows an approved private LiteLLM alias.
- Imported data source defaults are L1/L2. Any L3/L4 elevation must be explicit, evidence-backed, and audited.
- Logs must not include sensitive fields, API keys, or large raw content.
- Rule expressions cannot execute arbitrary code.
- AI output cannot bypass permissions, classification, masking, or rule guardrails.

## Acceptance Tests

P0 end-to-end cases:

- Static D4 PDF ingestion produces asset, version, parse artifact, normalized ref, AI run, `governance_result.quality_summary`, governance result, chunks, index manifest.
- D1 crawler JSON batch produces queryable raw package and searchable normalized records.
- High-confidence AI plus clean rules automatically enters `available`.
- AI/rule conflict enters `review_required` with evidence and conflict reason.
- Rule save-to-activate and re-governance generate updated `governance_result.decision_trail` and mark index stale if needed.
- Unauthorized caller cannot retrieve L3/L4 exception content.
- QA response includes source citations.
- Reprocess creates a new job/version and enters `available` or `review_required`.
- RAGFlow sync failure can be retried and traced in `index_manifest`.
- Duplicate `idempotency_key` does not create duplicate effective assets.
- Local identity works without DingTalk.
- AI re-score produces new `ai_governance_run` and updated `governance_result.quality_summary` while retaining feedback and score deltas in `decision_trail`.

Go / No-Go:

- Permission leakage rate must be 0.
- Traceability must be 100% for standardized assets, governance decisions, AI conclusions, and QA citations.
- Job failures must be locatable and retryable.
- Critical actions must be audited.
- Platform must work without external IAM.
