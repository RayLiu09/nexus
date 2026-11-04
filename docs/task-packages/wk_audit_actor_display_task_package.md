# Audit actor display task package

## Goal and source

Latest user instruction supersedes the earlier uniform `system` display rule:
show the actual recorded executor in the administrator audit list. Follow
ARCHITECT/SPEC audit traceability, Prototype NX-10 and WORKFLOWS Permission/Audit
and Frontend UX gates.

## Bounded contract and scope

- Remove system-type substitution from the API read model and Console cell.
- Resolve user/API Caller names as before; otherwise display the recorded
  `actor_id` (worker ID, scheduler, recovery or connector identifier).
- Missing actor IDs/names display `未记录`, including old system-type-only rows.
- Keep stored audit evidence, write attribution, API fields, authorization,
  redaction, event filtering and pagination unchanged. No migration/history
  backfill, new services, reverse pointers or unrelated worktree changes.
- Update focused API/UI assertions and ARCHITECT, SPEC, readme and Prototype.

## Verification and review

- API: `.venv/bin/python -m pytest tests/test_audit_log_list.py -q -o addopts=`
  from `nexus-api`: **13 passed**. Includes stored executor IDs for system,
  worker, scheduler, connector and repair types; system type without ID stays
  unknown; user/API names, redaction, batching and authorization remain covered.
- Console: `npm test -- app/iam-audit`: **7 passed**. Both resolved system
  executor names and raw worker-ID fallbacks are visible; the generic system
  label is absent. User names, unknown attribution and list interactions pass.
- `npm run typecheck` and `git diff --check` pass.
- Local preview API restarted with background runtimes disabled. Health is
  HTTP 200/status `ok`; the unauthenticated audit page redirects to login (307).
- API/UX contract review: no new storage writes, permission changes, schema or
  data migration; existing display-name redaction remains in force. Human
  review remains required before merge under WORKFLOWS. This task does not
  merge or publish changes.
