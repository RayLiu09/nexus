# Task Package: Pipeline B External-Call Transaction Boundary Fix

## Source Context

- `AGENTS.md`: P0 jobs use the PostgreSQL job table, lease/heartbeat, retry and
  dead-letter semantics; LiteLLM remains the model-routing boundary.
- `ARCHITECT.md`: mutations, state transitions and AI adoption remain auditable.
- `WORKFLOWS.md`: blocking-defect fixes require a bounded scope, test evidence,
  and the AI Governance / Version State review checks.

## Goal

Prevent Pipeline B job-demand LLM extraction from holding a database transaction
and the `job` row lock across an external LiteLLM call. Stages must remain
observable, the lease heartbeat must be able to renew, and failures must retain
the existing retry/audit semantics.

## Scope

- `nexus-app/nexus_app/worker/runner.py`
- the job-demand knowledge-extraction service and its focused tests
- worker transaction/heartbeat regression tests
- this task package

## Out Of Scope

- New APIs, Console UX changes, schema migrations, or a new async framework.
- Changing LiteLLM provider routing, prompt profiles, governance rules, or
  `governance_result` adoption rules.
- Broad transaction refactors outside the Pipeline B job-demand extraction path.

## Forbidden Changes

- Do not bypass LiteLLM, schema validation, audit writes, or governance
  guardrails.
- Do not manually mark a stalled job successful.
- Do not weaken job idempotency, retry/backoff, lease or state-machine rules.

## Deliverables

- A committed checkpoint before the external call.
- No open DB transaction while the LiteLLM call is in flight.
- Bounded in-memory parallel extraction for independent job-demand records;
  worker threads must not access the SQLAlchemy session.
- Focused regression tests proving stage visibility and heartbeat progress from a
  separate session during an intentionally blocked fake LLM call.
- Verification evidence and AI Governance / Version State self-review.

## Acceptance

- The job-demand extraction path preserves persisted dataset and traceability.
- During a blocked LLM call, a second DB session reads the actual job stage and
  can update `lock_expires_at` without waiting for the extraction transaction.
- Independent record calls execute concurrently up to the configured worker
  concurrency limit, while persistence remains deterministic and single-threaded.
- Successful and failed focused tests pass without real network calls.
