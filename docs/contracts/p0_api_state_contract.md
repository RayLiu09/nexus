# NEXUS P0 API And State Contract

Status: frozen for Week 1 implementation baseline

Source contracts:

- `ARCHTECT.md`
- `SPEC.md`
- `WORKFLOWS.md`
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`
- `docs/task-packages/wk_1_task_package.md`

This document is the Week 1 minimum shared contract for backend, frontend, tests, and docs. It intentionally freezes only the P0 surface needed for Week 1 and Week 2 "ingest to assetization" work.

## 1. Boundary Rules

- External business APIs are owned by `nexus-api` and use the `/v1` prefix.
- Console-only APIs may exist later in `nexus-console`, but must not become canonical business APIs for upper systems.
- NEXUS must not depend on enterprise IAM. Local identity and local org data are mandatory.
- DingTalk sync is optional and must not be a runtime dependency.
- NEXUS must not develop a self-owned `llm-gateway`; AI gateway routing stays in existing LiteLLM.
- Prompt management belongs to NEXUS through `ai_prompt_profile`.
- AI governance is inside `metadata-service.ai-governance`, not an independently deployed service.
- Governance input is `normalized_document` or `normalized_record`, never raw object payloads.
- Do not add reverse pointers:
  - no `document_asset.current_version_id`;
  - no `document_version.normalized_ref_id`;
  - no `document_version.quality_report_id` or equivalent quality-report reverse pointer.
- AI suggestions cannot become official governance results until schema validation, field whitelist, redaction, rule guardrails, confidence thresholds, and state-machine decisions pass.

## 2. Common API Shape

All `/v1` responses use stable JSON object envelopes.

Success envelope:

```json
{
  "data": {},
  "meta": {
    "trace_id": "01HX...",
    "page": 1,
    "page_size": 20,
    "total": 0
  }
}
```

List envelope:

```json
{
  "data": [],
  "meta": {
    "trace_id": "01HX...",
    "page": 1,
    "page_size": 20,
    "total": 0
  }
}
```

Error envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": []
  },
  "meta": {
    "trace_id": "01HX..."
  }
}
```

Required request and response rules:

- Every response includes `meta.trace_id`.
- Mutating APIs that can be retried must accept `Idempotency-Key` or an explicit `idempotency_key` field once they perform durable side effects.
- API keys, secrets, L3/L4 raw content, and large raw payloads must not be returned from general list APIs.
- Timestamps use UTC ISO 8601 strings.
- Resource IDs are UUID strings unless an external source identifier is explicitly named.

## 3. Frozen Status Enums

### Asset Version Status

| Value | UI Label | Searchable | Meaning |
|-------|----------|------------|---------|
| `processing` | 处理中 | No | Ingest, parse, standardization, governance, or index build is in progress. |
| `available` | 当前可用 | Yes | Version passed required normalized ref, quality, governance, rule, confidence, and uniqueness checks. |
| `review_required` | 需复核 | No | Manual review is required for quality, governance, sensitivity, permission, index, policy, or explicit rule reasons. |
| `archived` | 历史归档 | No by default | Historical version replaced by another version. |
| `disabled` | 已停用 | No | Manually disabled. |
| `failed` | 处理失败 | No | Unrecoverable processing failure. |

### Ingest Batch Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `submitted` | 已提交 | Batch accepted but raw persistence has not completed. |
| `raw_persisted` | 已落原始库 | Raw object ledger and object URI are recorded. |
| `processing` | 处理中 | Downstream jobs are running. |
| `completed` | 已完成 | Batch processing reached a terminal successful state. |
| `partial_failed` | 部分失败 | Some objects failed while others continued. |
| `failed` | 失败 | Batch failed before producing usable downstream results. |
| `duplicate_skipped` | 重复跳过 | Idempotency or checksum duplicate was detected and skipped. |

### Raw Object Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `raw_persisted` | 已落原始库 | Raw metadata and object URI are available. |
| `checksum_failed` | 校验失败 | Checksum or validation failed. |
| `duplicate_skipped` | 重复跳过 | Duplicate raw input skipped. |
| `failed` | 失败 | Raw persistence failed. |

### Job Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `queued` | 排队中 | Waiting for worker execution. |
| `running` | 处理中 | Worker is executing. |
| `succeeded` | 成功 | Job completed successfully. |
| `failed` | 失败 | Job failed and may or may not be retryable. |
| `review_required` | 需复核 | Job outcome requires manual review. |
| `dead_lettered` | 死信 | Retry policy exhausted or message moved to DLQ. |
| `cancelled` | 已取消 | Explicitly cancelled. |

### Index Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `not_indexed` | 未索引 | No index manifest exists. |
| `pending` | 待索引 | Waiting for RAGFlow indexing. |
| `building` | 索引中 | Index build is running. |
| `indexed` | 已索引 | Searchable projection exists. |
| `failed` | 索引失败 | Index build failed. |
| `stale` | 待重建 | Rules, governance, or content changed after index build. |
| `disabled` | 已停用 | Index disabled by policy or manual action. |

### AI Adoption Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `pending` | 待处理 | AI output not yet evaluated. |
| `auto_adopted` | 已自动采纳 | AI suggestions passed validation, confidence, and rule guardrails. |
| `partially_adopted` | 部分采纳 | Only a subset of AI suggestions was accepted. |
| `review_required` | 待复核 | Needs human review due to low confidence, conflict, sensitivity, or policy. |
| `rejected` | 已驳回 | Human or rules rejected the AI suggestion. |
| `overridden` | 人工覆盖 | Human changed one or more AI-proposed values. |

### Rule Set Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `draft` | 草稿 | Editable unpublished rule set. |
| `validating` | 校验中 | Validation is running. |
| `published` | 已发布 | Immutable active or selectable rule set version. |
| `disabled` | 已禁用 | Rule set cannot be used for new decisions. |
| `archived` | 已归档 | Historical retained version. |
| `validation_failed` | 校验失败 | Validation failed and publish is blocked. |

### Prompt Profile Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `draft` | 草稿 | Editable Prompt profile version. |
| `validating` | 校验中 | Variable whitelist, schema, redaction, weights, and model alias checks are running. |
| `published` | 已发布 | Immutable published Prompt version. |
| `active` | 当前启用 | Active Prompt profile for a task type. |
| `disabled` | 已禁用 | Cannot be selected for new AI runs. |
| `archived` | 已归档 | Historical retained version. |
| `validation_failed` | 校验失败 | Publish blocked by validation failure. |

### Data Source Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `enabled` | 启用 | Accepts new ingest batches. |
| `disabled` | 停用 | Does not accept new ingest batches. |
| `error` | 异常 | Source configuration or connectivity is abnormal. |

### Local Principal Status

| Value | UI Label | Meaning |
|-------|----------|---------|
| `active` | 启用 | Can be selected or used. |
| `disabled` | 停用 | Cannot initiate or receive new access. |
| `archived` | 已归档 | Historical retained object. |

## 4. UI Status Tone Map

| Tone | Use For |
|------|---------|
| `neutral` | Draft, archived, not indexed, submitted. |
| `info` | Processing, queued, pending, raw persisted, validating. |
| `success` | Available, succeeded, completed, indexed, enabled, auto adopted, published, active. |
| `warning` | Review required, partial failed, stale, partially adopted, validation failed. |
| `danger` | Failed, dead lettered, checksum failed, rejected, error. |
| `muted` | Disabled, cancelled, duplicate skipped. |

Frontend status label mappings must be generated from these values or kept in lockstep with this table.

## 5. P0 API Groups And Initial Paths

Week 1 implements only the bolded minimal endpoints. The remaining paths are frozen as names and high-level semantics for Week 2+.

### Health And Runtime

| Method | Path | Week 1 | Meaning |
|--------|------|--------|---------|
| GET | `/v1/health` | Yes | Liveness check. |
| GET | `/v1/runtime/state` | Yes | Basic runtime state for workbench. |

### Identity, Org, And API Callers

| Method | Path | Week 1 | Meaning |
|--------|------|--------|---------|
| POST | `/v1/org-units` | Yes | Create local org unit. |
| GET | `/v1/org-units` | Yes | List local org units. |
| GET | `/v1/org-units/{org_unit_id}` | Yes | Get local org unit. |
| POST | `/v1/users` | Yes | Create local user. |
| GET | `/v1/users` | Yes | List local users. |
| GET | `/v1/users/{user_id}` | Yes | Get local user. |
| POST | `/v1/api-callers` | Yes | Create API caller. |
| GET | `/v1/api-callers` | Yes | List API callers. |
| GET | `/v1/api-callers/{api_caller_id}` | Yes | Get API caller. |
| POST | `/v1/auth/verify` | No | Verify caller and optional end-user context. |
| POST | `/v1/api-keys` | No | API key creation, audited. |
| GET | `/v1/api-keys` | No | API key metadata list; never returns secret values. |

### Data Sources

| Method | Path | Week 1 | Meaning |
|--------|------|--------|---------|
| POST | `/v1/data-sources` | Yes | Create data source. |
| GET | `/v1/data-sources` | Yes | List data sources. |
| GET | `/v1/data-sources/{data_source_id}` | Yes | Get data source. |
| PATCH | `/v1/data-sources/{data_source_id}` | No | Update mutable fields. |
| POST | `/v1/data-sources/{data_source_id}:disable` | No | Disable source with audit. |

### Ingest And Raw Ledger

| Method | Path | Week 1 | Meaning |
|--------|------|--------|---------|
| POST | `/v1/ingest/batches` | Yes | Create ingest batch metadata. |
| GET | `/v1/ingest/batches` | Yes | List ingest batches. |
| GET | `/v1/ingest/batches/{batch_id}` | Yes | Get ingest batch. |
| GET | `/v1/raw-objects` | Yes | List raw objects. |
| GET | `/v1/raw-objects/{raw_object_id}` | Yes | Get raw object. |
| GET | `/v1/ingest/batches/{batch_id}/raw-objects` | No | List raw objects created by an ingest batch. |
| POST | `/v1/ingest/files` | No | Submit file upload and raw persistence. |
| POST | `/v1/ingest/crawler-packages` | No | Submit crawler JSON package. |

### Jobs

| Method | Path | Week 1 | Meaning |
|--------|------|--------|---------|
| GET | `/v1/jobs` | No | List jobs. |
| GET | `/v1/jobs/{job_id}` | No | Get job. |
| POST | `/v1/jobs/{job_id}:retry` | No | Retry failed job. |
| POST | `/v1/jobs/{job_id}:reprocess` | No | Reprocess related object. |
| POST | `/v1/jobs/{job_id}:re-governance` | No | Re-run governance. |

### Assets, Search, QA, Governance, Rules, Prompts

| Method | Path | Week 1 | Meaning |
|--------|------|--------|---------|
| GET | `/v1/assets` | No | List assets with derived current version read model. |
| GET | `/v1/assets/{asset_id}` | No | Get asset detail. |
| GET | `/v1/assets/{asset_id}/versions` | No | List asset versions. |
| POST | `/v1/search` | No | Permission-filtered search. |
| POST | `/v1/qa` | No | Permission-filtered QA with citations. |
| GET | `/v1/governance/decisions` | No | List governance decisions. |
| GET | `/v1/governance/ai-runs` | No | List AI governance runs. |
| POST | `/v1/governance/ai-runs/{run_id}:feedback` | No | Record feedback. |
| POST | `/v1/governance/ai-runs/{run_id}:rescore` | No | AI re-score request. |
| GET | `/v1/rule-sets` | No | List rule sets. |
| POST | `/v1/rule-sets` | No | Create draft rule set. |
| POST | `/v1/rule-sets/{rule_set_id}:validate` | No | Validate restricted expressions. |
| POST | `/v1/rule-sets/{rule_set_id}:publish` | No | Publish immutable rule set version. |
| POST | `/v1/rule-sets/{rule_set_id}:rollback` | No | Roll back to prior published version. |
| GET | `/v1/ai-prompt-profiles` | No | List Prompt profiles. |
| POST | `/v1/ai-prompt-profiles` | No | Create draft Prompt profile. |
| POST | `/v1/ai-prompt-profiles/{profile_id}:validate` | No | Validate Prompt profile. |
| POST | `/v1/ai-prompt-profiles/{profile_id}:publish` | No | Publish immutable Prompt profile. |
| POST | `/v1/ai-prompt-profiles/{profile_id}:disable` | No | Disable Prompt profile. |

## 6. Audit Event Baseline

Audit event names are frozen as PascalCase strings.

| Event | Required For |
|-------|--------------|
| `OrgUnitCreated` | Local org creation. |
| `OrgUnitUpdated` | Local org changes. |
| `UserCreated` | Local user creation. |
| `UserUpdated` | Local user changes. |
| `ApiCallerCreated` | API caller creation. |
| `ApiCallerUpdated` | API caller changes. |
| `ApiKeyCreated` | API key creation; secret value must not be logged. |
| `ApiKeyDisabled` | API key disable. |
| `DataSourceCreated` | Data source creation. |
| `DataSourceUpdated` | Data source updates. |
| `DataSourceDisabled` | Data source disable. |
| `IngestBatchSubmitted` | Batch submitted. |
| `RawObjectPersisted` | Raw object ledger and object URI persisted. |
| `JobRetryRequested` | Retry requested. |
| `ReprocessRequested` | Reprocess requested. |
| `ReGovernanceRequested` | Re-governance requested. |
| `VersionStatusChanged` | Version status transition. |
| `GovernanceResultWritten` | Official governance result written. |
| `HumanOverrideSubmitted` | Human override of AI or rules. |
| `AIAdoptionDecisionRecorded` | AI adoption state decided. |
| `AIRescoreRequested` | AI re-score requested. |
| `AIPromptProfileCreated` | Prompt draft created. |
| `AIPromptProfileValidated` | Prompt validation completed. |
| `AIPromptProfilePublished` | Prompt published. |
| `AIPromptProfileDisabled` | Prompt disabled. |
| `RuleSetCreated` | Rule set draft created. |
| `RuleSetValidated` | Rule set validation completed. |
| `RuleSetPublished` | Rule set published. |
| `RuleSetRolledBack` | Rule set rollback. |
| `PermissionDenied` | Authorization denied. |
| `SensitiveContentMasked` | L3/L4 content masked. |
| `SearchExecuted` | Search request completed. |
| `QAExecuted` | QA request completed. |

Every audit event must carry `trace_id`, actor or caller context, target resource type/id, event time, and a redacted summary.

## 7. Week 2 M1 Demo Path Draft

1. Create local org unit, platform user, API caller, and data source.
2. Submit a storage-backed ingest request for a D4 static document; the pipeline creates raw object ledger metadata with checksum and object URI.
3. View batch and raw object from raw ledger.
4. View job state placeholders from job center once Week 2 job orchestration is added.
5. Produce or simulate normalized reference and asset version.
6. Run AI governance and rules in Week 2+ implementation.
7. Version enters `available` when quality, governance, confidence, and uniqueness checks pass; otherwise `review_required`.
8. Asset catalog shows derived current version, not a stored reverse pointer.

## 8. Review Gate Notes

- API Contract Gate: `/v1` prefix, envelopes, error shape, status enums, and idempotency notes are frozen here.
- Version State Gate: only the six `document_version.version_status` values above are valid.
- Frontend UX Gate: P0 navigation must include NX-00 through NX-10 and NX-13, and must not include NX-11/NX-12 as P0 pages.
- Data Model Gate: Week 1 master data models must not add asset/version reverse pointers.
