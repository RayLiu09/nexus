# File Data Sync Console

## Source context

- `ARCHITECT.md`: source identity, raw retention, PostgreSQL jobs and audit remain in place.
- `SPEC.md` and Prototype v2.2: file upload and NAS are data access workflows.
- The current NAS scan-task endpoint accepts supplied items and does not scan a mounted directory.

## Goal

Make local file upload usable without manually registering a data source. Replace the Console data-source management entry with File Data Sync. Represent NAS as manual-only and unavailable until its backend exists.

## Scope

- Default upload source API and multi-file Console proxy.
- File Sync page, navigation, upload controls, history links and tests.
- Contract documentation for the changed Console workflow.

## Out of scope

- NAS filesystem scanner, connection probing, scheduling, database migration, crawler or API sync changes.

## Forbidden changes

- Do not remove the `data_source` backend entity or lineage relationships.
- Do not claim NAS synchronization works or display computed schedule times.
- Do not add MQ/Celery, an AI gateway, or alter governance input/state rules.

## Acceptance

- First local upload obtains one audited, enabled default file source without operator setup.
- Concurrent requests reuse that source; a disabled default source cannot accept new uploads.
- `/file-sync` is the navigation target; former `/data-sources` pages are unavailable.
- NAS is visibly manual-only and its sync action is unavailable.
- Backend and Console focused tests, typecheck, and Frontend UX/API Contract Gate review evidence.
