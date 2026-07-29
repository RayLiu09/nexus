# Task Package: API Caller Full Open API Access

## Goal

Make each newly minted API Caller key explicitly represent the full current
`/open/v1/*` capability. Remove Console controls whose arbitrary scope labels
do not map to P0 Open API route authorization.

## Scope

- Persist `permission_scope=["open:*"]` for new callers and legacy scope
  updates.
- Show the fixed effective permission in Console create, edit, and list views.
- Show a truncated SHA-256 key fingerprint in the Console list for
  server-minted callers; never redisplay plaintext keys or complete hashes.
- Record the effective scope in API-caller creation/update audits.
- Add focused API lifecycle regression coverage.

## Out Of Scope

- Per-route restricted Open API scopes, quota enforcement, org/data-level
  policy changes, database backfills, and changes to `/open/v1` endpoints.

## Acceptance

- Creating a caller returns and persists `["open:*"]`, including when a
  legacy client sends an empty or arbitrary scope array.
- Updating a legacy scope cannot remove the full Open API capability.
- Console no longer offers misleading per-route scope selection.
- API caller lifecycle tests and Console static/type checks pass.
