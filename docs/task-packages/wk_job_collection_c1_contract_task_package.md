# Task Package: Job Collection C1 Upstream Contract

## Source Context

- `docs/api_data_sync_framework_implementation_plan.md` and `docs/contracts/api_data_sync_contract.md`: file-backed Provider Catalog, immutable plans, provider-owned protocol, no external calls in database transactions.
- `docs/上游应用对接岗位数据爬虫服务方案.html`: crawler-api Job lifecycle and cursor-based record reads.
- `docs/岗位数据归一化及岗位词典库建设技术方案.html`: sync batches retain raw facts; subsequent snapshot-based job processing is an independent domain, not Pipeline B or generic AI governance.
- Live OpenAPI at `http://10.100.11.51:8080/openapi.json`, inspected on 2026-10-08; API version `0.2.0`.

## Goal

Freeze the verified crawler-api wire schema, provider query boundary, status mapping, and raw-record handoff before implementing the real adapter or result receiver.

## Scope

- Document the upstream auth, submit, status, control, and records endpoints and their request/response shapes.
- Identify discrepancies between the live OpenAPI, older integration guide, and NEXUS runtime assumptions.
- Define the minimum raw-record identity and page checkpoint rules for the next task packages.

## Out Of Scope

- Creating a live collection Job, changing upstream state, adding a Provider to the deployed Catalog, or storing the tenant key.
- Adapter implementation, migrations, result receiver, Console changes, and job normalization.

## Forbidden Changes

- Do not commit real tenant credentials, access tokens, raw job responses, or a private Provider Catalog.
- Do not route raw job JSON through Pipeline B `normalized_record` / `normalized_asset_ref` or generic AI governance.
- Do not add external HTTP calls inside database transactions.

## Deliverables

- `docs/contracts/job_collection_provider_contract.md` with confirmed schema and explicit unresolved runtime semantics.
- This bounded task package and verification evidence.

## Review Gates

- API Contract: validate schema and error/status behavior against an authorized integration test.
- Data Model and Permission/Audit: review the raw result receiver design before its implementation.

## Acceptance And Evidence

- Live OpenAPI returned HTTP 200 and declared API version `0.2.0` on 2026-10-08.
- Its component schemas and paths were inspected with `jq`; no tenant key or token was sent during this read-only check.
- C1 is complete when the documented OpenAPI facts are accurate and unresolved behavior is clearly marked for C2 integration testing.
