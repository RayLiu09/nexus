# Governance Review Decision Review Evidence

## 2026-11-05: Retired Asset Review Guard

- Pending review candidates now join the asset and exclude `archived` and
  `disabled` assets before SQL pagination/counting. Latest-result and newer
  visible-version filtering remain in place.
- Review context and new decision submission reject retired assets with 409.
  State-machine retirement errors are translated to the same conflict; the
  endpoint rolls back the transaction. Other state-transition errors become
  validation errors (422). Successful decision replay remains idempotent.
- Version State/API Contract review: the existing state manager remains the
  transition authority; no status enum, schema, migration, role boundary or
  public business API changes. Historical decisions and AI evidence remain.
- User requested committing and pushing this scoped fix on 2026-11-05.

Validation (isolated SQLite; no production database access):

```text
cd nexus-api
.venv/bin/python -m pytest tests/test_governance_review_pagination.py tests/test_governance_review_queue_performance.py -q
7 passed (rerun outside sandbox: 3.11s)

cd nexus-app
.venv/bin/python -m pytest tests/governance/test_review_service.py tests/governance/test_version_state_smoke.py -q
9 passed

git diff --check
```

API TestClient execution stalled inside the sandbox after the two unit tests;
the complete API selection passed outside the sandbox. New regressions cover
archived-asset queue exclusion, HTTP 409 mapping and rejection before new
decision/result writes. Existing tests also verify bounded queue queries,
pagination/counts, stale-version filtering, review replay and continuation/audit
behavior. Disabled-asset and concurrent-retirement branches were reviewed in
code but do not have dedicated new regression cases in this patch.

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
