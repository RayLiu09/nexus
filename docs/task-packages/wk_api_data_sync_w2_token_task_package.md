# Task Package: API Data Sync W2 Configured Credentials And Token

## Source Context

- `docs/api_data_sync_framework_implementation_plan.md` W2 and `docs/contracts/api_data_sync_contract.md`.
- W0/W1 provides the file-backed Provider Catalog, Mock adapter, and read-only credential status.
- `WORKFLOWS.md` requires architecture, permission, and audit review for credential handling.

## Goal

Read tenant credentials directly from the Provider Catalog and provide cached access tokens with bounded 401 refresh for future sync-run requests.

## Scope

- Provider Catalog validates non-empty `tenant_id`, `tenant_name`, and `tenant_key`. Real deployment Catalog files remain private and outside version control.
- Adapter-owned Mock Token endpoint/protocol, exercised through `httpx.MockTransport`.
- Shared in-process Token Manager with expiry, invalidation, one 401 refresh retry, and 401/403/timeout/invalid-response classification.
- Catalog API reports credential availability without returning the configured key.
- Focused tests and contract/plan updates.

## Out Of Scope

- No real provider, run table, scheduler, Worker, Console Token action, or persisted token.
- No external Secret Resolver or extra secrets file.
- No Token API URL in Catalog config or user API.

## Forbidden Changes

- Never store a real tenantKey in version control, DB, audit, API response, exception message, or log. The deployment Catalog is the one allowed configuration location for the key.
- Do not hardcode tenant ID/name/key in adapter.
- Do not retry 403 or a second 401.
- Do not introduce Redis or a new gateway.

## Acceptance

- Mock Token Server sees configured tenant ID and key at runtime; changed Catalog values need no adapter code change.
- Cached token is reused until expiry; 401 invalidates and retries once; 403 stops immediately.
- Token API timeout and malformed body have distinct safe error codes.
- Missing or empty `tenant_key` fails Catalog validation; the Provider view never includes the configured key.

## Review Gates

- Architecture Review and Permission And Audit Gate completed, as confirmed by the project owner on 2026-09-30.

## Verification Evidence

- `nexus-app`: `uv run pytest tests/data_sync/test_catalog.py tests/data_sync/test_plans.py tests/data_sync/test_tokens.py` -> 20 passed.
- `nexus-api`: `uv run pytest tests/test_data_sync_catalog_api.py tests/test_data_sync_plans_api.py` -> 4 passed.
- `git diff --check` -> clean.
- Tests cover configured tenant parameters, token reuse and expiry, a single 401 refresh, 403 without retry, Token API 401/403/5xx/timeout/malformed responses, and absence of tenantKey from Provider API and error/log text.
- Human Architecture and Permission And Audit reviews were completed on 2026-09-30.
