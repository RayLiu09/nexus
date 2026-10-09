# Task Package: Job Collection C2 Live Verification

## Source Context

- `docs/contracts/job_collection_provider_contract.md`: OpenAPI 0.2.0 schema and unresolved live semantics.
- `docs/contracts/api_data_sync_contract.md`: immutable plan, idempotent run, synchronous controls, safe audit, and no external call inside a database transaction.
- User-provided test query: source `zhaopin`, keyword `数据化运营助理`, region `杭州市`, pageLimit `10`.

## Goal

Verify the real crawler-api protocol with one authorized collection Job and record enough evidence to implement the NEXUS adapter and result receiver correctly.

## Scope

- Exchange the tenant key for a Caller Token in memory and inspect scopes/expiry without revealing the token.
- Submit one Job with a stable request ID and idempotency key; retry the same submit to check replay behavior.
- Observe status, exercise pause/resume when the Job is controllable, and inspect control response versus actual status.
- Read records with an opaque cursor, inspect field presence and pagination, and check terminal/empty-page behavior.
- Record only safe IDs, counts, statuses, HTTP codes, and schema findings in a verification report.

## Out Of Scope

- Adapter implementation, private Catalog file, schema migration, result persistence, Console changes, and job normalization.
- A second collection Job solely to test cancellation, unless it becomes necessary and is separately authorized.

## Forbidden Changes

- Do not put the tenant key, Caller Token, full raw responses, or job descriptions in source control, process output, or the verification report.
- Do not cancel the only collection Job before the requested result pages are available.
- Do not infer local `paused` or `cancelled` solely from an HTTP 200 control response.

## Review Gates And Acceptance

- API Contract review: compare actual responses and error codes against the C1 contract.
- Permission/Audit review: verify required scopes and credential redaction.
- Result receiver remains a separate Data Model review task.
- Verification evidence states which checks passed, failed, or could not be exercised and why.

## Verification Evidence

- `docs/review/job_collection_c2_live_verification.md` records the live Job ID, HTTP status codes, lifecycle, 49-record pagination, optional-field gaps, and unresolved checks without credentials or raw job content.
- API Contract and Permission/Audit Review Gates remain pending human review.
