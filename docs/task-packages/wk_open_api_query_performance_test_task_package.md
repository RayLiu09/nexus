# Task Package: Open API Query Performance Test

## Source Context

- `ARCHITECT.md`: `/open/v1/*` is the API-caller boundary; public reads must
  preserve available-version and governance visibility gates.
- `SPEC.md`: catalog and retrieval reads have explicit P95 targets; API keys
  and sensitive content must never be emitted in logs or evidence.
- `WORKFLOWS.md`: non-trivial work requires bounded evidence and the relevant
  permission/audit and acceptance checks.

## Goal

Measure the registered, authenticated `/open/v1` query endpoints against the
current development data set and publish a one-page decision report plus an
endpoint domain-distribution view.

## Scope

- Read-only black-box requests to documented `/open/v1` query endpoints.
- Fixed, bounded warm-up and load samples with API-caller authentication.
- Endpoint inventory classification, latency/error aggregation, and report.

## Out Of Scope

- API implementation, schema, database, governance, permissions, or indexes.
- Mutating external-search routes, Query Router POST routes, and SSE routes.
- Production capacity certification or a load test against an unapproved
  shared production environment.

## Forbidden Changes

- Do not persist, log, or report plaintext API keys, request headers, raw
  business content, or L3/L4 content.
- Do not weaken API-caller authentication, available-version filtering, audit,
  or governance visibility rules.
- Do not start pipeline workers or crawler scheduling as part of the test.

## Deliverables

- A reproducible bounded test harness with redacted output.
- One-page Markdown performance report with environment, method, results,
  findings, and limitations.
- An Open API query endpoint domain-distribution diagram.

## Acceptance

- Every measured request is authenticated and read-only.
- The report gives endpoint-level sample counts, P50/P95/P99, throughput, and
  status distribution, without secret or business-content disclosure.
- The domain diagram accounts for every documented query endpoint and clearly
  identifies excluded non-query/mutating/streaming routes.
