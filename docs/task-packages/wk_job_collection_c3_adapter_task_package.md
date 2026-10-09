# Task Package: Job Collection C3 Provider Adapter

## Source Context

- `docs/contracts/job_collection_provider_contract.md` and `docs/review/job_collection_c2_live_verification.md`: live crawler-api 0.2.0 wire schema and observed status/pagination behavior.
- `docs/contracts/api_data_sync_contract.md`: Provider-owned protocol, immutable plans, Token refresh, and no external call inside a database transaction.
- `docs/岗位数据归一化及岗位词典库建设技术方案.html`: raw posting processing is an independent domain.

## Goal

Implement a tested `crawler_engine` adapter for token exchange, query validation, Job submission/status, record pagination, and controls, using only deployment-supplied Provider configuration.

## Scope

- Add `nexus_app.data_sync.adapters.crawler_engine:CrawlerEngineDataSyncProvider`.
- Validate one keyword/region/pageLimit query and map it to the upstream `zhaopin` Job request.
- Parse camelCase Token/Job/record responses, classify HTTP and malformed-response failures without logging secrets or raw content.
- Preserve complete parsed record dictionaries and opaque cursors in adapter output.
- Add focused MockTransport contract tests and a private-Catalog loading test.
- Document activation prerequisites discovered by C2.

## Out Of Scope

- Real tenant key in the repository, enabled production Catalog entry, live Job creation, result sink, migration, Console UI, and job normalization.
- Shared runtime/control state-machine changes, which require a separate API Contract Review Gate.

## Forbidden Changes

- No external HTTP calls inside database transactions.
- No successful live run that discards fetched records or treats `pausing` as `paused`.
- No raw response bodies, access tokens, or tenant keys in logs and error messages.

## Deliverables And Acceptance

- Adapter module and tests covering Token errors, 401 refresh compatibility, query validation, idempotent submit headers, status mapping, pagination, control response states, and safe failures.
- Verification command: `.venv/bin/python -m pytest tests/data_sync -q` from `nexus-app`.
- Provider remains absent from the enabled default Catalog until durable result intake and control-state behavior are reviewed and implemented.

## Verification Evidence

- Focused adapter contract tests and the full `tests/data_sync` suite passed (45 tests).
- `compileall` passed for the adapter module. Ruff was unavailable in the project environment.
- The existing enabled Catalog still contains only the Mock Provider. A test-only Catalog loads the real adapter through its trusted factory reference with a fake credential.
- API Contract Review Gate for live control-state semantics and Data Model Review Gate for durable result intake remain open.
