# Worker Lease And Knowledge Continuation Recovery Evidence

Date: 2026-07-28

## Scope

- Task package: `wk_worker_lease_continuation_recovery_task_package.md`.
- Files: `nexus_app/worker/loop.py`, `nexus_app/worker/runner.py`, and focused
  Worker lifecycle tests.
- No model, migration, API, governance-result, or review-decision changes.

## Contract Review

| Gate | Evidence |
| --- | --- |
| Version State | Dependency bootstrap failures now leave `running` through the existing `_mark_job_outcome` path, which clears the lease and applies normal retry/dead-letter policy. No asset/version transition is changed. |
| Semantic Retrieval | A `knowledge_continuation` still invokes only `run_knowledge_chunking` and `run_index_submit`; it does not run ingest, parse, normalize, or governance. MinerU is no longer initialized for this path. |
| Permission And Audit | The one recovered job received a `KnowledgeContinuationQueued` audit row with a recovery reason, prior state, prior attempt count, target normalized ref, and knowledge-only scope. |

## Automated Verification

```text
UV_CACHE_DIR=/tmp/nexus-uv-cache uv run pytest \
  tests/test_worker_lease_lifecycle.py \
  tests/governance/test_review_service.py \
  tests/governance/test_pipeline_integration.py -q

27 passed
```

```text
UV_CACHE_DIR=/tmp/nexus-uv-cache uv run python -m compileall -q \
  nexus_app/worker tests/test_worker_lease_lifecycle.py
```

`ruff` is not installed in this project's resolved environment, so no Ruff
command was available for this run. `git diff --check` passed.

## Controlled Production Recovery

Target job: `0c3035bb-c30e-479f-b980-387268df6b9c`

Preconditions checked before the update:

- `job_type=knowledge_continuation`
- `status=dead_lettered`
- `attempt_count=3`, `max_attempts=3`
- `normalized_ref_id=fb96858c-32a7-4a8e-b8f4-c9d2ef6cdd6c`
- `trigger=governance_review`

Recovery reset only that job's lease/error fields and attempt budget, then
recorded an audited `KnowledgeContinuationQueued` event. It did not modify the
immutable review decision or governance-result rows.

Observed terminal result:

- job status: `succeeded` (attempt count: `1` after recovery)
- successful new stages: `knowledge_chunking`, `index_submit`
- index manifest: `68387afd-ecdb-4065-b2ff-168ab30885c6`
- knowledge type: `industry_research_kb`
- index status: `indexed`
- chunk count: `1289`
