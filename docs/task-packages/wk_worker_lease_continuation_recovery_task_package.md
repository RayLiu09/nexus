# Task Package: Worker Lease And Knowledge Continuation Recovery

## Source Context

- `AGENTS.md`: P0 asynchronous execution uses PostgreSQL jobs, row-level
  claiming, lease heartbeat, retry/backoff and dead-letter recovery; the
  knowledge pipeline remains independent and is anchored on
  `normalized_asset_ref`.
- `ARCHITECT.md`: a governance-review decision may resume only knowledge
  chunking and indexing. The resulting state must remain traceable and
  recoverable.
- `WORKFLOWS.md`: worker state, version state and semantic retrieval changes
  require focused tests and Version State / Semantic Retrieval review evidence.

## Goal

Prevent a claimed job from losing its lease while Worker dependencies are being
initialized, avoid unnecessary MinerU initialization for knowledge-only jobs,
and recover the identified dead-lettered governance-review continuation without
re-running ingestion or governance.

## Scope

- Start the lease heartbeat before pre-execution dependency initialization.
- Initialize Storage and MinerU lazily according to persisted job type and
  persisted pipeline payload.
- Persist initialization failures through the existing job outcome mechanism.
- Add focused Worker lifecycle regression tests.
- Requeue only job `0c3035bb-c30e-479f-b980-387268df6b9c` after the code fix.

## Out Of Scope

- Changes to governance-review decisions, governance-result snapshots,
  knowledge chunking/indexing semantics, queue schema, or broad dead-letter
  administration UI/API.

## Forbidden Changes

- Do not rerun parsing, normalization, LiteLLM governance, or manual review.
- Do not modify immutable `governance_review_decision` or historical
  `governance_result` rows.
- Do not infer a pipeline type from source content; use the persisted job
  payload only.
- Do not reset or requeue unrelated jobs.

## Deliverables

- Worker lifecycle fix with focused tests.
- Explicit audit evidence for the single recovered job.
- Review evidence documenting the lease and knowledge-continuation checks.

## Acceptance

- Heartbeat starts before any Storage/MinerU initialization after claiming.
- A `knowledge_continuation` job never initializes MinerU.
- Dependency initialization failure cannot leave a job in `running`.
- The identified continuation job returns to `queued` with a new lease attempt
  budget and subsequently executes only knowledge chunking/index submission.
