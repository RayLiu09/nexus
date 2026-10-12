# Console Quick Upload Role Boundary

## Source context

- `SPEC.md` assigns ingestion to platform/data administrators and governance review to business experts.
- Prototype v2.2 section 3.2 requires role visibility on key actions.
- `WORKFLOWS.md` requires Frontend UX and Permission And Audit review for this P0 interaction.

## Goal

Business experts cannot see or use Quick Upload; administrators retain the existing flow.

## Scope

- Console Topbar visibility and focused component tests.
- Console multi-file ingest proxy role check and focused route tests.

## Out of scope

- Backend ingest contracts, data models, other upload workflows, and role definitions.

## Forbidden changes

- No enterprise IAM, new gateway, new role, or governance contract changes.

## Acceptance

- A business expert sees no Quick Upload action and receives 403 from its upload endpoint.
- An administrator can still open Quick Upload and submit through the proxy.
- Focused tests, typecheck, lint, and `git diff --check` pass.

## Review Gates

- Frontend UX: the Topbar remains usable with or without the action.
- Permission And Audit: role denial happens before backend proxy calls; existing backend authentication and audit remain in force.
