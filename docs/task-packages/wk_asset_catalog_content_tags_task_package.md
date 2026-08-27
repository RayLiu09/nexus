# Task Package: Asset Catalog Content Tags

## Source Context

- `ARCHITECT.md`: `governance_result` is anchored to
  `normalized_asset_ref`; current-version information is a derived read model.
- `ARCHITECT.md`: official governance tags are required for an available
  asset and must not be substituted with raw AI output.
- Prototype v2.2 NX-06: the asset catalog includes a tag field.
- `WORKFLOWS.md`: this is a bounded internal API and Console UI contract
  change with focused API and frontend verification.

## Goal

Hide the asset catalog's organization-scope and current-version table columns,
and add a content-tags column that presents the official AI-governance result
associated with the catalog row's selected normalized reference.

## Scope

- `nexus-app/nexus_app/schemas.py`: add `content_tags` to the internal catalog
  read schema.
- `nexus-api/nexus_api/api/internal/assets.py`: project the already batch-read
  latest `governance_result.tags` into each catalog row without new queries.
- `nexus-api/tests/test_asset_catalog_api.py`: assert the catalog response
  contains the official tags and retains its bounded-query behavior.
- `nexus-console/app/assets/_lib/types.ts`: add the internal read field.
- `nexus-console/app/assets/_components/AssetsContent.tsx`: remove only the
  organization-scope and current-version table columns, then add a content-tags
  column showing up to three tags and an overflow tooltip.
- `nexus-console/app/assets/_components/AssetsContent.test.tsx`: verify the
  removed column and rendered official tags.

## Out Of Scope

- Asset-detail, governance-review, IAM, permission, or audit presentation of
  organization scope or current version.
- Governance decision writes, AI prompt/run output, tag taxonomy, tag indexes,
  migrations, and public `/open/v1/assets` API shape.
- New catalog filter behavior or clickable tags.

## Forbidden Changes

- Do not expose `ai_governance_run.ai_output` as a catalog tag source.
- Do not change `governance_result` ownership away from
  `normalized_asset_ref`.
- Do not add a data-model migration, reverse pointer, or per-row database
  query.
- Do not alter catalog visibility, status, permissions, or tag-search
  semantics.

## Deliverables

- Internal catalog read-model field and Console table replacement.
- Focused backend contract/performance regression test and frontend render
  test.

## Acceptance

- `/internal/v1/assets` returns `content_tags` from the official latest
  governance result for the catalog's selected normalized reference, or `[]`.
- The `/assets` table has no `组织范围` or `当前版本` column and renders
  `内容标签` compactly.
- Catalog query count remains bounded; no N+1 query is introduced.
- Focused backend tests and Console type/test checks pass.
