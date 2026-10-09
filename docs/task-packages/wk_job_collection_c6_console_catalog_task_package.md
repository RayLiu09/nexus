# Task Package: Job Collection C6 Catalog And Console

## Goal

Replace the Mock Provider console experience with a job-collection plan form backed by a database job-title catalog and fixed city options.

## Scope

- Add professional-category and job-title master tables, seed the 76 rows from `docs/76个岗位.xlsx` using only the job-name column, and expose a read-only internal catalog endpoint.
- Change the crawler adapter query contract to multiple cities and job names with page choices 10/30/50/100 (default 30); submit the Cartesian product as upstream queries, bounded by the upstream 100-query limit.
- Show only the job-collection Provider and its plans in Console. Use a right drawer with city multi-select, category-filtered job-name multi-select, and page select.
- Update tests and architecture/API documentation.

## Out Of Scope

- CRUD management for master data, other professional categories, and job normalization.
- Changes to crawler-api. Its current `pageLimit` maximum is 30; NEXUS can persist 50/100 for rollout when upstream expands.

## Forbidden Changes

- No Mock Provider deletion from backend test fixtures.
- No tenant key in committed files or API responses.
- No external HTTP calls inside a database transaction.
- No Pipeline B or generic AI governance coupling.

## Acceptance

- Database stores one category and 76 source rows; the catalog endpoint presents 74 distinct selectable names because `视觉设计师` occurs three times in the source.
- Multi-select plans validate DB-backed title membership, fixed regions, page values and the 100-query limit.
- Console hides Mock and creates a crawler plan with selected arrays and default 30 pages.
- Adapter sends one upstream query for each selected title/city pair.
