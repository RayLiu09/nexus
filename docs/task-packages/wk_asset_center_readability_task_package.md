# Task Package: Asset Center Readability

## Goal

Improve the Asset Center overview as a readable business asset dashboard. Give domain headings, descriptions, resource names, and counts comfortable type sizes and clear space from card boundaries.

## Scope

- `/asset-center` overview card typography, spacing, and responsive resource layout.
- Focused component verification and desktop/mobile visual inspection.

## Out Of Scope

- Resource routes, counts, permissions, API contracts, and domain registry entries.

## Forbidden Changes

- Do not add decorative dashboard data or alter asset ownership or governance state.

## Acceptance

- Four visible domain cards retain their links and counts.
- Text and counts fit without collision at narrow and wide widths.
- Header and resource rows have consistent interior spacing and readable hierarchy.
- Component test, typecheck, lint, and Frontend UX Review Gate visual inspection pass.

## Verification Evidence

- Playwright inspection at 1440x900 and 390x844: four cards visible, no page or resource-row horizontal overflow, and no text/count collision.
- Computed card header padding is 24px on wide screens and 20px/24px on narrow screens; resource links have 12px interior padding.
