# Task Package: Job Collection C7 Submit Recovery And Pause Clarity

## Goal

Recover a crawler submit whose response is lost, and make plan pause versus run pause clear during live verification.

## Scope

- Replay an unconfirmed submit with the same frozen query, run-derived external request ID, and idempotency key; keep genuine 409 conflicts terminal.
- Preserve retry eligibility for an unconfirmed submit across ordinary retry and expired worker leases.
- Surface transitional upstream control states and make the existing run-pause action reachable after pausing a plan.
- Add focused adapter, runtime, API-control, and Console tests.

## Boundaries

- Do not add an upstream lookup endpoint, a new database table, or an asynchronous control-request mechanism.
- Do not change the rule that pausing a plan stops future scheduling but does not control an existing run.
- Keep external HTTP outside database transactions and credentials out of logs and committed files.

## Acceptance

- A response-lost submit replays identically and recovers the existing upstream Job ID.
- Unconfirmed submits remain retryable after the normal attempt cap; a 409 conflict remains a safe terminal error.
- Plan pause exposes the run-history action; run pause shows an accepted transition until upstream confirms `paused`.
