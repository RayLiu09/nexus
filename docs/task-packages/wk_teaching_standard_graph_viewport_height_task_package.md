# Task Package: Teaching Standard Graph Viewport Height

## Source Context

- User request: make the professional teaching standard's 职业领域图谱 height
  adapt to the window.
- Prototype v2.2 and the teaching-standard business-view task package: the
  graph opens in a right Drawer with download, fullscreen, and node details.
- `WORKFLOWS.md`: bounded frontend changes and verification evidence.

## Goal And Scope

Enable the shared capability graph's existing `viewportHeight` mode in
`TeachingStandardsTable.tsx`, replacing this entry's fixed 560px canvas with
the established dynamic-viewport sizing used by occupational analysis.
The existing ResizeObserver resizes the ECharts canvas when its box changes.

## Out Of Scope And Forbidden Changes

- No graph data, topology, query, API, permissions, or state changes.
- No new sizing mechanism or changes to other graph callers.
- No changes to original-download, fullscreen, or node-detail behavior.

## Acceptance And Verification

- Opening 职业领域图谱 enables the existing viewport-height mode.
- The canvas follows window height with the existing 280px minimum and
  1000px maximum and resizes without reloading graph data.
- Run the existing teaching-standard component tests, TypeScript check, and
  scoped ESLint; inspect viewport sizing in a browser where available.
- This is a small layout correction within the existing UX contract.
  No API, architecture, or product-contract changes are introduced.

## Verification Evidence

- Existing `TeachingStandardsTable.test.tsx`: 2 tests passed.
- `npm run typecheck`: passed.
- Scoped ESLint using the repository's Next.js, core-web-vitals, and TypeScript
  presets: passed. The normal config could not load the existing missing
  `eslint-plugin-testing-library`; a temporary config omitted only test-file
  plugins for checking this production component.
- `git diff --check`: passed.
- Live-page browser validation was not performed; no Console server was
  listening on ports 3000/3001 during this change.
