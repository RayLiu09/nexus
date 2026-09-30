# Task Package: Crawler First-Level Console Page

## Goal

Move the existing Crawler plan workflow from the Data Sources type view to a dedicated administrator navigation page.

## Scope

- Add `/crawler` to the administrator navigation and render the existing plan list and creation drawer there.
- Remove the Crawler type card and embedded plans from Data Sources.
- Redirect old `?type=crawler` and new-source deep links to `/crawler`.

## Forbidden Changes

- Do not change Crawler API, plan semantics, run behavior, or stored data sources.

## Review Gate

- P0 Frontend UX review before merge.

## Verification

- TypeScript, focused lint, route build, and old-link redirect checks.
