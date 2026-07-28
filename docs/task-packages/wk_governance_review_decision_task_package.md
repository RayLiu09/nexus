# Task Package: Immutable Governance Review Decision

## Source Context

- `AGENTS.md`: governance inputs and results target `normalized_asset_ref`;
  AI suggestions need schema/rule/threshold checks before becoming official;
  mutations and human overrides must be audited; `available` is derived by the
  existing version state machine.
- `ARCHITECT.md` and `SPEC.md`: AI governance keeps raw AI runs separate from
  official governance results and requires human-review traceability.
- `WORKFLOWS.md`: this is a data-model, AI-governance, version-state,
  permission/audit, semantic-retrieval and API-contract change.

## Goal

Replace the Console's non-persistent tag-review mock with an immutable
governance-review decision that lets a business expert finalize classification,
level, structured retrieval tags, quality disposition, and org scope. The
decision creates a new official governance snapshot and resumes only the
existing knowledge stages when the resulting version is admissible.

## Scope

- Add immutable `governance_review_decision` persistence, migration, schemas,
  audit events, and a focused domain service.
- Add Console-internal pending/context/history/submit APIs protected by the
  existing local user session and mutating-request idempotency key.
- Add `knowledge_continuation` job execution that reuses `run_knowledge_chunking`
  and `run_index_submit` without re-running ingest, parsing, normalize, or AI.
- Remove deprecated `rejected` adoption semantics in favor of
  `review_required`, `human_confirmed`, and `human_overridden`.
- Replace `/tag-review` interaction with a pending governance-review queue and
  a single `提交治理结论` action; remove the low-value auto-submit history.
- Update focused contracts/docs/tests.

## Out Of Scope

- Prompt/rule-taxonomy redesign, automatic quality-score rewriting, raw-file
  review, bulk review, external business APIs, a second orchestration service,
  and historical data compatibility/backfill. This development environment has
  no persisted `rejected` decision data.

## Forbidden Changes

- Do not mutate `AIGovernanceRun.ai_output`, rerun LiteLLM, or overwrite the
  source `GovernanceResult` when an expert submits a decision.
- Do not introduce reverse current-result pointers or bypass
  `VersionStateManager` to force `available`.
- Do not treat free-form flat strings as final human retrieval tags; final
  tags must validate as `StructuredTagBag`.
- Do not delete AI `governance_tag` evidence rows; expert-final tags use the
  existing `expert_manual` source.
- Do not infer a continuation pipeline type at runtime; persist it in the
  continuation job payload at creation.

## Deliverables

- Immutable review decision plus new official governance-result snapshot.
- Auditable expert tag projection and admissibility reevaluation.
- Idempotent continuation Job that resumes knowledge chunking/indexing only.
- Console governance-review queue and Drawer.
- Data model, AI governance, version-state, audit, API, worker, and Console
  regression tests.

## Acceptance

- A reviewer can submit one final governance conclusion with a valid
  classification, level, structured tags, quality disposition, org scope and
  reason; the raw AI run and base result remain unchanged.
- Invalid AI suggestions become `review_required`; no new `rejected` decision
  status is emitted.
- A passing final decision creates `expert_manual` `tag_asset_index` rows,
  becomes the latest governance result, transitions the version through the
  existing state manager, and queues a knowledge-only continuation job.
- A non-admissible review persists the decision and manual tags but keeps the
  version `review_required` and does not queue external indexing.
- Submission is idempotent and rejects stale base-result submissions with 409.
- All human submissions, state transitions, and continuation jobs are audited
  with actor and trace ID.

## Review Gates

- Data Model Gate
- AI Governance Gate
- Version State Gate
- Permission And Audit Gate
- Semantic Retrieval Integration Gate
- API Contract Gate
- Frontend UX Gate
