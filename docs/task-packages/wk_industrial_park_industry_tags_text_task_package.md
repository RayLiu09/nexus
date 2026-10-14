# Task Package: Industrial Park Industry Tags As Text

## Source Context

- `SPEC.md`: Market Asset Center park list.
- `WORKFLOWS.md`: Data Model, API Contract, and Frontend UX Review Gates.
- `docs/task-packages/wk_market_catalog_api_counts_task_package.md`: existing park catalog.

## Goal

Store park industry tags as readable text and make the industry filter match Chinese tags.

## Scope

- `industrial_park.industry_tags` migration and ORM mapping.
- Sample importer, internal park list/export API, Console park table and type.
- Focused migration and API verification; contract documentation.

## Out Of Scope

- Enterprise data model, other Asset Center resources, external business APIs.

## Forbidden Changes

- Preserve existing park and enterprise IDs, counts, and internal route paths.
- Do not change governance, identity, or pipeline contracts.

## Deliverables And Acceptance

- Existing JSON arrays migrate to readable `、`-separated text; new imports use the same format.
- `/internal/v1/industrial-parks?industry=数字经济` filters persisted Chinese tags.
- Console and Excel display text; focused tests and type checking pass.
- Data Model, API Contract, and Frontend UX Review Gate review before merge.
