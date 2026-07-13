# Task Package: Pipeline External-Call Transaction Boundaries

## Source Context

- `AGENTS.md`: P0 jobs use PostgreSQL row-claim leases and heartbeat; LiteLLM,
  MinerU, object storage, embeddings, and the retrieval adapter are external
  dependencies and must not compromise job recovery.
- `ARCHITECT.md`: Pipeline A/B retain auditable state transitions and NEXUS
  owns the normalized/governance/index records.
- `WORKFLOWS.md`: this is a blocking pipeline reliability fix requiring the
  AI Governance, Version State, and Semantic Retrieval review checks.

## Goal

Remove remaining cases in Pipeline A/B where a long external operation can run
while the worker session holds uncommitted writes or a `job` row lock.

## Scope

- Normalize LiteLLM enhancement and normalized-payload storage boundary.
- Multi-stage AI governance LiteLLM boundary.
- Pipeline B body-markdown render and task-description structuring boundaries.
- pgvector embedding and legacy RAGFlow index-submit boundaries.
- Focused regression tests for transaction visibility during blocked fakes.

## Out Of Scope

- New job framework, schema migration, API/Console changes, provider routing,
  governance rules, or retrieval ranking behavior.
- Request-time retrieval/QA paths and batch backfill scripts.

## Forbidden Changes

- Do not bypass LiteLLM, schema validation, redaction, field whitelists,
  rule guardrails, audit records, idempotency, or version-state rules.
- Do not turn an external-call failure into a successful pipeline outcome.

## Deliverables

- Durable running stage/checkpoint before a long external operation.
- External blocks use immutable input snapshots and no SQLAlchemy session.
- Short result-persistence transactions with existing audit and retry behavior.
- Regression tests proving no transaction is active during representative LLM
  and embedding calls.

## Acceptance

- A separate heartbeat session can renew a running job while a fake external
  call is blocked.
- Existing Pipeline A/B state and governance tests remain green.
- Each affected operation remains idempotent on retry.
