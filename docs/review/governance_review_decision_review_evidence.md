# Governance Review Decision Review Evidence

Date: 2026-07-28

## Delivered Scope

- `governance_review_decision` is immutable and links the source official
  governance result to the resulting official result snapshot.
- Business experts submit classification, level, structured taxonomy tags,
  quality disposition/reason, org scope, and review reason through the
  Console-internal API.
- Human tags are projected as `tag_asset_index.source=expert_manual`; AI
  `governance_tag` evidence is retained.
- `VersionStateManager` remains the sole version-state transition authority.
- An available conclusion creates an idempotent `knowledge_continuation` job
  carrying the original persisted ingest `pipeline_type`; the worker invokes
  only knowledge chunking and index submission.
- `GOVERNANCE_REVIEW_DECISION_SUBMITTED`, `VERSION_STATUS_CHANGED`, and
  `KNOWLEDGE_CONTINUATION_QUEUED` share the request trace ID.

## Review Gates

| Gate | Evidence |
| --- | --- |
| Data Model | One-way `GovernanceReviewDecision -> resulting GovernanceResult` relationship; no current-result reverse pointer added. |
| AI Governance | Source AI run and source governance result are never mutated; review validates active classification/level rules and structured tags. |
| Version State | Final result is re-evaluated by `VersionStateManager`; only final human/auto adoption states can be available. |
| Permission and Audit | Submit endpoint permits `business_expert` and `platform_data_admin` only; mutation requires `Idempotency-Key`; all key actions are audited. |
| Semantic Retrieval | Continuation job is only queued for `available`, uses persisted queue-time routing, and reuses existing chunk/index stages. |
| API and UX | `/tag-review` is now the persistent governance-review queue with a single `提交治理结论` action and no auto-submit history. |

## Verification

```text
uv run pytest nexus-app/tests/governance/test_review_service.py \
  nexus-app/tests/governance/test_decision_service.py \
  nexus-app/tests/governance/test_redaction.py \
  nexus-app/tests/governance/test_version_state_smoke.py -q
27 passed

cd nexus-console && npm run lint -- --quiet
cd nexus-console && npm run typecheck
```
