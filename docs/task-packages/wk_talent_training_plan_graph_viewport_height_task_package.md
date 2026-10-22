# Task Package: Talent Training Plan Graph Viewport Height

## Source Context

- User request: adapt both 课程知识图谱 and 岗位能力图谱 to the window.
- Prototype v2.2 and `wk_talent_training_plan_business_view_task_package.md`:
  both graphs are lazy-loaded Drawers with download and fullscreen actions.
- The preceding teaching-standard fix uses the shared viewport-height pattern.

## Goal And Scope

Update only `TalentTrainingPlanGraphView.tsx` sizing so both graph kinds
use dynamic viewport height rather than a fixed 620px canvas. In fullscreen,
fill the existing modal body without enforcing the previous 520px minimum.
Retain the existing ResizeObserver for ECharts updates on container resize.

## Out Of Scope And Forbidden Changes

- No API, graph data, topology, generation, state, permission, or audit changes.
- No changes to other graph renderers or the shared fullscreen modal.
- Preserve lazy loading, missing-evidence messages, tooltips, zoom/pan,
  download, and fullscreen controls.

## Acceptance And Verification

- Both graph kinds use the existing `clamp(280px, calc(100dvh - 200px), 1000px)`
  sizing convention when embedded in their Drawer.
- Fullscreen charts fill the available modal body and may shrink below 520px.
- Run existing graph-view and list-view tests, TypeScript, scoped production
  ESLint, and `git diff --check`.
- This is a bounded layout correction within the established UX contract;
  product, architecture, and API contracts stay applicable.

## Verification Evidence

- Existing graph-view and list-view component tests: 2 files, 4 tests passed.
- `npm run typecheck`: passed.
- Scoped production ESLint with the repository's Next.js, core-web-vitals,
  and TypeScript presets: passed. As in the preceding task, a temporary config
  excludes the unavailable test-only plugins from the production-file check.
- `git diff --check`: passed.
- Live-page browser validation was not performed. Component tests verify
  existing lazy-loading and list interactions, not browser geometry.
