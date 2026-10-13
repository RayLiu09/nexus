# Task Package: Market Catalog API Counts And Labels

## Source Context

- `ARCHITECT.md`, `SPEC.md`: Asset Center business projections and internal Console APIs.
- `WORKFLOWS.md`: API Contract and Frontend UX Review Gates.
- `docs/task-packages/wk_business_asset_center_ia1_task_package.md`: market resource routes and on-demand counts.

## Goal

Show the existing industrial park and enterprise data through the Asset Center API with truthful counts, and use the requested market resource names.

## Scope

- Asset Center count query and focused API tests.
- Market resource labels, legacy classification display labels, empty states, and export filename.
- Existing internal park/enterprise list API and Console route verification.

## Out Of Scope

- New ingestion pipelines, governance classifications, schema migrations, or external business APIs.
- Rewriting historical `job_demand` governance results.

## Forbidden Changes

- Do not change stable classification codes or the existing park/enterprise API response schema.
- Preserve authorization on internal Console routes and existing architecture boundaries.

## Acceptance

- `/internal/v1/asset-center/counts` reports actual park and enterprise row totals.
- Park and enterprise list endpoints return the corresponding persisted rows.
- The Asset Center displays `市场岗位` and `产业园区`.
- Focused API/UI tests and type checking pass.
