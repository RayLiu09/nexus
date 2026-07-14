# Task Package: Catalog Auxiliary Panels Removal

## Source context

- `AGENTS.md`: P0 Console surfaces should support operational work without
  decorative or explanatory side panels.
- `WORKFLOWS.md`: UI changes require scoped ownership and verification.

## Goal

Remove non-operational right-side auxiliary panels from the asset catalog and
tag-review pages so the tables and review workflow occupy the primary surface.

## Scope

- `nexus-console/app/assets/_components/AssetsContent.tsx`
- `nexus-console/app/assets/_components/DomainDistribution.tsx`
- `nexus-console/app/assets/_lib/types.ts`
- `nexus-console/app/tag-review/_components/TagReviewContent.tsx`
- focused catalog CSS and this task package.

## Out of scope

- Asset catalog APIs, summary metrics, filters, pagination, or detail links.
- Tag review data loading, audit behavior, bulk actions, and review drawer.

## Acceptance

- Asset catalog has no right-side data-distribution or explanatory panels.
- Tag review has no right-side tag-flow explanation panel.
- Main table/workflow surfaces use the available width.
- `npm run typecheck` passes.
