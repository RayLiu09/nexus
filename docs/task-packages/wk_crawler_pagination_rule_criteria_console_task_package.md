# Task Package: Crawler Pagination and Governance Rules Console Repair

## Goal

Restore working pagination for Crawler plans and show the existing classification and tag judgment evidence in Rules configuration.

## Scope

- Use the Crawler plan list API's `page`, `pageSize`, and `total` in the Console table. Default to 20 rows per page; offer 20, 50, and 100.
- Show classification description, title keywords, and content keywords as judgment criteria when the rule has no explicit `criteria` list.
- Render current `tag_dimensions` and per-classification tagging basis in the Data Tags section.
- Add focused Console regression tests for page changes and criteria rendering.

## Out of Scope

- Governance rule definitions, rule engine behavior, API schema, database changes, and crawler execution.

## Acceptance / Frontend UX Gate

- The plan table requests the selected page and size from the API and shows the API total.
- There is no 8-row page option; the initial choice is 20 rows.
- Classification judgment criteria display the existing source fields, including keywords, without inventing new rule conditions.
- Data Tags shows the five configured dimensions and their fixed options or per-classification values and criteria.
- Focused tests, typecheck, and lint pass.
