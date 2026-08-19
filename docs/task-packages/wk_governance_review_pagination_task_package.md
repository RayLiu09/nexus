# Task Package: Governance Review Pagination

## Goal

Make the governance-review queue usable beyond its first result page and show
the navigation pending-review badge from the complete queue count.

## Source Context

- `WORKFLOWS.md`: changed internal API consumption and P0 console workflows
  require API Contract and Frontend UX verification.
- `nexus_api.dependencies.pagination`: all list APIs use `page` and
  `pageSize`, with `meta.total` as the complete result-set count.

## Scope

- Existing `GET /internal/v1/governance-reviews/pending` metadata consumption.
- Console review-queue server proxy, page state, table pagination, and nav
  badge count.
- Focused regression tests for paginated queue metadata.

## Out Of Scope

- Changes to governance-review decision semantics, role permissions, queue
  ordering, review history, or new query filters.

## Frozen Contract

- The queue is server-paginated with `page` and `pageSize`; `meta.total` is
  the count of all latest `review_required` results, not the current page.
- The review table requests each selected page and never relies on local
  pagination of a truncated initial response.
- The navigation Badge uses the same `meta.total` count.

## Acceptance

- A queue above 100 rows can navigate to all pages and preserves the correct
  total after page changes.
- The Badge count equals the full pending queue, including items beyond the
  first page.
- Existing review submission reloads the current page and updates its total.
