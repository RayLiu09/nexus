# Task Package: Course Textbook Knowledge Graph Viewport Height

## Source Context

- User request: make the course textbook knowledge radial graph and outline
  tree height adapt to the viewport in Asset Center.
- Existing Asset Center graph views use viewport-based sizing with a bounded
  `clamp(280px, calc(100dvh - 200px), 1000px)` height and ResizeObserver.
- `WORKFLOWS.md`: frontend UX fixes remain bounded and require verification
  evidence.

## Goal And Scope

Update the shared course textbook knowledge-outline chart so both radial and
left-to-right tree modes follow the available viewport height while retaining
the existing fullscreen behavior, graph data, interactions, and downloads.

## Out Of Scope And Forbidden Changes

- No graph data, topology, query, API, permissions, or state changes.
- No changes to task-outline views or other graph callers.
- No changes to node details, original download, or fullscreen behavior.

## Deliverables And Acceptance

- The normal knowledge radial and outline tree canvases use the established
  bounded viewport-height sizing.
- The ECharts ResizeObserver continues to resize the canvas after viewport or
  drawer layout changes.
- Component tests cover both graph modes and the viewport-height class.
- Run the focused component test, TypeScript check, scoped lint, and
  `git diff --check`.
