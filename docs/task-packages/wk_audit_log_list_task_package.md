# Task Package: Administrator Audit Log List

Display-only revision: the latest user instruction supersedes this package's
original uniform `system` label with recorded executor IDs. See
`wk_audit_actor_display_task_package.md` for the current display contract.

## Source Context

- User request (2026-11-04): rename the administrator's 权限与审计 entry to
  审计日志, show a dedicated list, filter Token refresh events, allow event-type
  filtering, and display system processing actors as `system`.
- `ARCHITECT.md`: local identity, sanitized audit summaries, derived read models.
- `SPEC.md` and Prototype v2.2 NX-10: auditable actor, action, target and time.
- `WORKFLOWS.md`: Permission And Audit, API Contract and Frontend UX gates.

## Goal And Scope

- Rename the navigation and `/iam-audit` page; remove unrelated identity counts
  and API Caller table from this page.
- Show event type, target type, target name, actor, summary and operation time.
- Filter and paginate in SQL, with the filtered total; fetch event choices from
  the complete log set rather than just the current page.
- Resolve common target/actor names using bounded, batched scalar reads.
- Add focused API/UI tests and update contract documentation.

## Frozen Contract

- `GET /internal/v1/audit-logs` retains `page`, `pageSize`, response envelope and
  existing fields. Add optional `event_type` and `exclude_token_refresh=false`.
  Filtering precedes count/offset/limit. Sort by `created_at DESC, id DESC`.
- Add nullable read fields `target_name` and `actor_name`; no schema migration.
  Use only safe names and sanitized audit snapshots, never credentials or raw
  content. Unknown/deleted targets fall back to snapshot names or full IDs.
- `GET /internal/v1/audit-logs/event-types` returns distinct recorded event
  strings and supports the same Token exclusion flag. Both reads require a
  platform data administrator; unauthenticated users receive 401, experts 403.
- Console always requests `exclude_token_refresh=true`, removing both
  `TokenRefreshed` and `TokenRefreshFailed` from rows, totals and event options.
- Console uses the `event_type` URL filter; existing workbench `event` links
  remain accepted. Changing event type resets the page, retains page size.
- System/worker/scheduler/connector identities display `system`. Missing
  historical actor attribution stays `未记录`; explicit user/caller IDs are
  never mislabeled as system. This task does not repair historical attribution.
- No implicit 30-day cutoff; all retained non-refresh events are pageable.

## Out Of Scope And Forbidden Changes

- No changes to audit write coverage, asset deletion/retention, event enums,
  governance, state transitions, credentials or business APIs.
- No new IAM service, gateway, database relation or redundant reverse pointer.
- Do not include other ongoing worktree changes in this slice.

## Acceptance And Review Evidence

- API tests: SQL filtering/totals, pagination beyond 100 rows, Token events
  retained in storage, event choices beyond the current page, safe name
  resolution/fallback, system and missing-actor semantics, 401/403.
- UI tests: six required columns, human-readable names, system display,
  event selection/reset, pagination preserving filter and page size, empty/error
  state. Typecheck and focused lint pass.
- Demo: administrator -> 访问与审计 -> 审计日志 -> select event type -> next page
  -> clear filter. Human merge review remains governed by `WORKFLOWS.md`.

## Verification Evidence (2026-11-04)

- API: `.venv/bin/python -m pytest tests/test_audit_log_list.py
  tests/api/test_pagination.py -q` — **32 passed**. Ran outside the sandbox
  because its restriction stalls Starlette TestClient's AnyIO portal startup.
- Console: `npm test -- app/iam-audit lib/navigation.test.ts` — **17 passed**.
- `npm run typecheck` — passed.
- Targeted Next.js/Core Web Vitals/TypeScript ESLint rules over the audit
  components and changed Console libraries — **0 errors, 0 warnings**.
  The repository ESLint config cannot load because its existing imports of
  `eslint-plugin-testing-library` / `eslint-plugin-vitest` are not installed;
  no dependency/config changes were made for this task. Test-plugin rules
  were therefore not verified.
- Permission And Audit review: admin dependency before reads; 401/403 tested;
  safe scalar-name projection; legacy summaries sanitized on read; original
  actor IDs, target IDs and trace IDs retained; refresh events stay in storage.
- API Contract review: existing envelope, pagination and fields retained;
  optional names and filters are documented; read-only, no migration/idempotency
  or governance-state changes. All supported target joins execute in tests.
- Frontend UX review: renamed navigation/page, six list columns, visible error
  and empty states, filter reset and page-size preservation tested.
- Human merge review is still required by `WORKFLOWS.md`; this task does not
  claim that automated evidence substitutes for that approval.
