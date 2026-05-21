# NEXUS Product Spec Contract v3.0

This document is the concise product and requirement contract for implementation. It is distilled from `docs/企业数据与知识资产平台需求Spec_v2.2.md` and `docs/企业数据与知识资产平台nexus_v8.0.md`, and is constrained by the v3.0 architecture baseline in `ARCHITECT.md`.

## Product Goal

NEXUS一期 builds the minimum usable loop for enterprise data assets and knowledge assets:

`data ingestion → ingest_validate → assetize → parse/normalize → normalized_asset_ref → AI governance and quality scoring → rule guardrails → available/review_required → RAGFlow indexing → permission-filtered search/QA → traceable citation and audit`

The platform focuses on D1-D4 pilot domains. Knowledge Pipeline P0 scope = Pipeline 1 (RAG retrieval KB) only. D5/D6 ingestion, knowledge graph, SFT corpus, evaluation standard library, and an operations center are not productized in P0.

## Roles

| Role | Scope |
|------|-------|
| 平台/数据管理员 | Local identity/org, data sources, ingestion, jobs, rules, AI Prompt configs, governance review, permissions, audit |
| 业务专家 | Rule review, AI suggestion review, quality calibration, normalize-service rule definition, search testing, knowledge asset review |
| 运维人员 | Basic job/runtime troubleshooting, retry where authorized, failure summaries |
| API 调用方 | Upper systems, smart apps, integrations, and authorized business access through API keys and user context |

Role constraints:
- No enterprise IAM/SSO required. Local identity mandatory; DingTalk sync optional.
- `nexus-console` APIs are internal control-plane only. Business-facing APIs belong in `nexus-api`.

## P0 Scope

- Local org/user/API caller management.
- Data source registration and file/NAS/crawler ingestion.
- Raw object retention and ingest ledger.
- `ingest_validate` job stage: format validation, virus scan, hash calculation, deduplication; writes `INGEST_VALIDATE_COMPLETED` / `INGEST_VALIDATE_FAILED` audit events.
- `assetize` job stage: create/re-version `asset`/`asset_version` by `(data_source_id, source_object_key)` idempotency anchor.
- Persistent job center backed by PostgreSQL job table + Worker polling, state machine, failure lookup, retry, lock lease, and dead-letter handling.
- MinerU parsing (Pipeline A): auto-selected `model_version` (HTML→MinerU-HTML, default→pipeline, complex→vlm); OCR auto-enabled for image/pdf/tiff; images stored at `parsed/<version_id>/<artifact_id>/images/`.
- Standardization via normalize-service: LLM semantic extraction + rule-engine fallback validation; produces `normalized_document` / `normalized_record` with full `normalized_asset_ref` fields (governance, quality, lineage, source_type, content_type, title, language).
- AI governance and quality scoring from normalized objects via `metadata-service.ai-governance`. Governance target is `normalized_asset_ref`.
- Configurable governance rules for classification, level, tags, org scope, quality admission, review triggers, and index admission.
- Governance decision tracking in `governance_result.decision_trail`.
- RAGFlow integration for chunking, indexing, search execution. `knowledge_chunk.normalized_ref_id` links chunks to `normalized_asset_ref`.
- Knowledge Pipeline 1: RAG retrieval KB for D4 teaching materials and D3 talent cultivation plans. Knowledge Pipeline is independent of Asset Pipeline.
- `metadata_enrich` auto-tagging: targets normalized assets (not chunks); high-confidence tags auto-commit (audit logged); low-confidence tags enter human review queue.
- RBAC, org scope filtering, data-level visibility, masking for L3/L4 exceptions, audit. ABAC is an extension point.
- `nexus-console` P0 pages and `/v1` P0 APIs.
- Search/QA source traceability to asset version, normalized ref (with image_uris), chunk, and raw object.
- Basic maintainability: health checks, structured logs, trace IDs, job status, basic runtime state.

## P1 Scope

- Optional DingTalk org sync.
- Retrieval test console.
- Basic knowledge asset management.
- API Key operation enhancements.
- Basic reports for assets, quality, search, API calls.
- Rule effect analysis.
- AI effect analysis.
- Consumption-side audit events: `AssetVersionAccessed`, `SearchQueryExecuted`, `QAAnswerGenerated` written by search/QA handlers in `nexus-api`. These events are the data foundation for Phase 2 consumption-side data lineage analysis.

## P2 Reserved

- D5/D6 production ingestion.
- Knowledge Pipeline 2 (QA corpus / SFT), Pipeline 3 (process corpus), Pipeline 4 (knowledge graph), Pipeline 5 (evaluation standard library).
- Productized operations center for release, monitoring, alerting, capacity planning.
- Prompt automatic optimization, LiteLLM alias A/B comparison, active learning, batch AI re-scoring strategy.
- Full high availability upgrades.

## Console Information Architecture

P0 pages:

- **工作台**: ingestion/job/review/AI adoption/rule overview/basic runtime state.
- **数据源管理**: source registration, upload entry, NAS sync, crawler push config.
- **数据接入**: single file, batch upload, directory import, ingestion policy.
- **原始数据台账**: batch query, raw object query, checksum, replay entry.
- **作业中心**: job list, stage progress (including ingest_validate / assetize / parse / normalize), failure reason, retry, reprocess, re-governance.
- **资产目录**: asset list, current version read model, versions, normalized refs (with governance/quality/lineage fields), index status.
- **资产详情**: overview, versions, normalized refs, AI governance, quality score, governance result, decision tracking, chunks (with normalized_ref_id), index manifest, lineage (including image_uris), audit.
- **治理中心**: AI suggestions, AI quality score, AI Prompt config, review tasks, rule config, save-to-activate changes, decision tracking, quality review.
- **规则配置**: structured editor for `config/governance_rules.json` (classifications, levels, tags, quality scoring, knowledge types); ETag-based concurrency control; save takes effect immediately for future governance runs.
- **权限与审计**: local users, roles, API keys, org scopes, approvals, audit logs.
- **AI Prompt 配置**: Prompt templates, LiteLLM alias references, output schema, scoring weights, redaction policies.
- **标签审核**: tag draft review (confirm / revise / reject), auto-committed tag history.

P1 pages:
- 检索测试
- 知识资产管理 (Knowledge Pipeline 1 assets)
- DingTalk 同步（可选）
- API Key 运营增强
- 统计报表

## Data Classification And Level

Assets are classified into D1-D6 domains with 3-level hierarchy. Default level:
- D1-D2: L1/L2. D3: L1/L3 (official→L1, school-private→L3). D4: L2/L3.
- D5-D6 (P2): L3/L4.

Imported data sources default to L1/L2. L3/L4 requires explicit source approval, governance rule evidence, manual/security review, and audit.

Level inheritance: asset → asset_version → normalized_document → knowledge_chunk. Can be overridden upward per-version or per-chunk if higher sensitivity detected.

## Governance Behavior

AI governance:
- Input: `normalized_document` or `normalized_record` (via `normalized_asset_ref`).
- Output pipeline: schema validation → field whitelist → redaction policy → `governance_rules.json` threshold checks (confidence_threshold_auto_adopt, quality pass/warning, level requires_approval) → state-machine decision (available / review_required).
- Results persisted in `ai_governance_run`. Human feedback in `governance_result.decision_trail`.
- High-confidence AI + quality pass → `available`. Low-confidence AI or quality below threshold → `review_required`.

Rules and decisions:
- Business rules live exclusively in `config/governance_rules.json` (file-based, single source of truth). Edits via console must pass schema validation, ETag optimistic locking, and fcntl exclusive write lock; saves take effect immediately for future governance runs and do not retroactively re-govern existing assets.
- Rules cover classifications, levels, tags, quality scoring (dimensions, check_items, thresholds, confidence_threshold_auto_adopt), and knowledge types.
- `governance_result.decision_trail` must record input summary, AI Prompt config, LiteLLM alias, Prompt version, AI suggestion, quality score, `rules_schema_version` + `rules_content_hash` (rules snapshot), final value, confidence, adoption status, and review reason (when entering `review_required`).

Auto-tagging:
- `metadata_enrich` generates tag drafts from normalized asset content (not chunks — they don't exist yet).
- High-confidence tags (≥ threshold) auto-committed with audit log. Admins can retrospectively review and revoke.
- Low-confidence tags queued for human review: confirm / revise / reject.

Search and QA:
- Search and QA must enforce permissions before returning content.
- Results must cite asset version, normalized ref, chunk ID (with normalized_ref_id), and source position including image_uris where applicable.
- Unauthorized or masked content must never be returned.
- Search handler must write `SearchQueryExecuted` audit event (query hash, hit normalized_ref_ids, caller_id) before returning results.
- QA handler must write `QAAnswerGenerated` audit event (question hash, cited normalized_ref_ids, cited chunk_ids, caller_id) before returning answer.
- These audit events must not contain query plaintext, answer content, or L3/L4 data.

## Public API Groups

P0 API groups include:

- Identity/org/API caller management.
- Data sources.
- Ingest submit and batch query.
- Raw object query.
- Job query, retry, reprocess.
- Asset list/detail/version/current read model.
- Search and QA.
- Governance rules read/edit (`config/governance_rules.json` via `/v1/admin/governance-rules`, ETag-protected).
- Governance decision query.
- AI Prompt profile query/create/update (save-to-activate)/disable/version query.
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
- MinerU parse success rate: ≥ 95%.

Security:
- L3/L4 exception content is masked by default.
- External models cannot receive unmasked L3/L4 plain text unless policy allows an approved private LiteLLM alias.
- Imported data source defaults are L1/L2. Any L3/L4 elevation must be explicit, evidence-backed, and audited.
- Logs must not include sensitive fields, API keys, or large raw content.
- `governance_rules.json` writes go through schema validation; the API never executes user-supplied code or expressions.
- AI output cannot bypass permissions, classification, masking, or `governance_rules.json` threshold checks.

## Acceptance Tests

P0 end-to-end cases:

- Static D4 PDF ingestion: `ingest_validate` passes → `assetize` creates asset/version → MinerU parse with auto-selected `model_version` produces `parse_artifact` with image URIs stored in `parsed/…/images/` → normalize produces `normalized_document` with full governance/quality/lineage fields in `normalized_asset_ref` → AI governance run → `governance_result.quality_summary` → governance result → chunks (with `normalized_ref_id`) → index manifest.
- HTML file ingestion: `model_version = MinerU-HTML` auto-selected; parse succeeds and images stored alongside JSON.
- Image/scanned PDF ingestion: `ocr_enable = true` auto-set; parse succeeds.
- D1 crawler JSON batch: `ingest_validate` passes → `assetize` (Pipeline B, no MinerU) → `normalized_record` with full `normalized_asset_ref` fields → queryable and searchable.
- High-confidence AI + quality pass → `available`.
- Low-confidence AI or quality below threshold → `review_required`, with reason recorded in `governance_result.decision_trail`.
- Tag generation: high-confidence tags auto-committed with audit log; low-confidence tags appear in review queue.
- Same `source_object_key` + different content re-ingested → new `asset_version`, old `available` archived; `AssetVersionArchived` audit event written.
- Rule edit (`config/governance_rules.json`) and re-governance → updated `governance_result.decision_trail`, index marked stale if needed.
- Unauthorized caller cannot retrieve L3/L4 exception content.
- QA response includes source citations with `normalized_ref_id` and image_uri references where applicable.
- Reprocess creates new job/version → `available` or `review_required`.
- RAGFlow sync failure retried and traced in `index_manifest`.
- Duplicate `idempotency_key` → no duplicate effective assets.
- Local identity works without DingTalk.
- AI re-score produces new `ai_governance_run` and updated `governance_result.quality_summary` while retaining feedback in `decision_trail`.
- Knowledge Pipeline 1: normalized D4 asset → RAGFlow chunked → chunk carries `normalized_ref_id` → search returns result traceable to normalized ref.

Go / No-Go:
- Permission leakage rate must be 0.
- Traceability must be 100% for standardized assets, governance decisions, AI conclusions, and QA citations.
- Job failures must be locatable and retryable.
- Critical actions must be audited.
- Platform must work without external IAM.
- `normalized_asset_ref` must include full v3.0 fields (governance, quality, lineage, source_type, content_type, title, language).
