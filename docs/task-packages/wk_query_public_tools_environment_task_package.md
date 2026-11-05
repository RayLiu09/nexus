# Task Package: Public Query Tool Environment Configuration

## Status

Configuration implemented and locally verified, 2026-11-04. Configuration prerequisite for the phase-one Chatbot refactor; runtime wiring is completed in the Chat phase-one package.

## Source Context

- User decision: public business HTTP requests use server environment variable `BUILDIN_API_CALLER`.
- User decision: search-result ingestion is controlled by `INGEST_SEARCH_RESULTS`, default false.
- User decision: `BUILDIN_API_BASE_URL` is environment-configurable, default `http://127.0.0.1:8000`.
- `ARCHITECT.md` / `SPEC.md`: reuse existing public APIs, caller authentication, normalized asset processing and traceability.
- `WORKFLOWS.md`: scoped changes, verification evidence and Permission And Audit review before merge.

## Goal And Scope

Add typed server configuration, write the supplied credential only to ignored local `.env.dev`, and update the phase-one technical plan. Document that the future tool executor injects the credential and overrides external-search `auto_ingest` from configuration. Preserve the initiating user separately from the API caller.

Allowed files: `nexus-app/nexus_app/config.py`, focused configuration tests, ignored root `.env.dev`, this package, and `docs/intelligent_search_phase1_technical_plan.md`.

## Out Of Scope And Forbidden Changes

- No new routes, caller creation, permission changes, migrations, external requests or real ingestion.
- Do not alter existing public search endpoint behavior or the legacy Query Router in this configuration slice.
- Do not commit credentials, expose them to the browser/model, or log their values.
- Do not bypass existing ingestion validation/governance or present queued web results as governed assets.
- Preserve unrelated workspace changes.

## Frozen Contract

- `Settings.buildin_api_caller`: optional masked `SecretStr`, alias exactly `BUILDIN_API_CALLER`; absent credentials are not hardcoded.
- `Settings.ingest_search_results`: boolean, alias `INGEST_SEARCH_RESULTS`, default false.
- `Settings.buildin_api_base_url`: string, alias `BUILDIN_API_BASE_URL`, default loopback API origin; executor validates origin before use.
- Future phase-one executor: requests to existing public APIs use this server credential; search `body.auto_ingest` is injected/overridden from the flag, never decided by model arguments.
- The flag applies to intelligent-search tool execution; independent public API consumers retain their existing contract.
- True queues qualifying results into the existing asset pipeline; it does not directly mark them available or governed.

## Acceptance And Evidence

- Isolated settings tests verify default false, true/false environment parsing, malformed values rejected, and credential masking in repr / JSON.
- Local verification reports only whether configuration is present, not its value; `.env.dev` remains ignored and untracked.
- Runtime use and audit identity propagation remain part of the subsequent tool executor implementation; this slice claims only configuration readiness.

Verification completed: `PYTHONPATH=nexus-app nexus-api/.venv/bin/python -m pytest nexus-app/tests/test_query_tool_config.py -q` — 6 passed (including configurable API origin). `git diff --check` passed. Local Settings loaded a nonempty masked credential and false ingestion flag; `git check-ignore` and `git ls-files` confirmed `.env.dev` is ignored and untracked. No network calls or ingestion were performed.

## Review Gate

Permission And Audit: inspect secret handling and future API-caller / initiating-user distinction before merge. No HTTP contract or live data changes in this slice.
