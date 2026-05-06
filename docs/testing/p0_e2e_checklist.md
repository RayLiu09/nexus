# P0 E2E Checklist Draft

Source: `SPEC.md` acceptance tests and `docs/task-packages/wk_1_task_package.md`.

This file is a Week 1 checklist. It is not the full automated E2E suite yet.

## M1 Week 2 Demo Assertions

1. Local identity works without DingTalk.
2. A platform/data admin can create an org unit, user, API caller, and data source through `/v1`.
3. A D4 static document batch can be represented as `ingest_batch` plus `raw_object` with checksum and object URI.
4. Reusing the same `idempotency_key` for the same source does not create a second effective ingest batch.
5. Reusing the same raw object checksum in the same source scope is detected by a unique constraint.
6. Health and runtime state return `trace_id`.
7. Logs and response bodies do not expose API keys, secrets, L3/L4 exception plain text, or large raw content.
8. Console P0 routes load and use the same status labels as the shared contract.
9. Console Week 1/2 pages render live `/v1` data for data sources, ingest batches, raw objects, jobs, assets, asset detail, and audit logs.
10. `scripts/week2_console_e2e.sh` can create a small ingest flow through API and confirm the live objects are visible through Console pages.

## P0 Full Flow Cases To Automate Later

1. Static D4 PDF ingestion produces asset, version, parse artifact, normalized ref, AI run, `governance_result.quality_summary`, governance result, chunks, and index manifest.
2. D1 crawler JSON batch produces queryable raw package and searchable normalized records.
3. High-confidence AI plus clean rules automatically enters `available`.
4. AI/rule conflict enters `review_required` with evidence and conflict reason.
5. Rule save-to-activate and re-governance update `governance_result.decision_trail` and mark index stale if needed.
6. Unauthorized caller cannot retrieve L3/L4 exception content.
7. QA response includes source citations.
8. Reprocess creates a new job/version and enters `available` or `review_required`.
9. RAGFlow sync failure can be retried and traced in `index_manifest`.
10. Duplicate `idempotency_key` does not create duplicate effective assets.
11. Local identity works without DingTalk.
12. AI re-score produces new `ai_governance_run` and updated `governance_result.quality_summary` while retaining feedback and score deltas in `decision_trail`.

## Permission Cases

1. Cross-org access denied by default.
2. L3/L4 exception content masked by default.
3. API caller scope narrower than user scope wins.
4. Disabled API caller cannot access business APIs.
5. Permission denied events produce `PermissionDenied` audit entries.

## Audit Cases

1. Prompt save-to-activate and disable are audited.
2. Rule save-to-activate, validate, and disable are audited.
3. Version status change is audited.
4. AI adoption, human override, and AI re-score are audited.
5. API key create and disable are audited, with secret values redacted.
