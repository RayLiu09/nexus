# Task Package: Teaching Standard Leaf Labels and Market Search Layout

## Source Context

- User request: show professional teaching-standard graph leaf content directly;
  rename park/enterprise `查询` to `检索` and align with other list toolbars.
- `SPEC.md` and Prototype v2.2: teaching standards reuse the evidence-bound
  professional/occupational/task/requirement graph; list filters use the upper
  right toolbar.
- `WORKFLOWS.md`: bounded frontend corrections with verification evidence.

## Goal And Scope

- Enable normal-state labels for teaching-standard graph leaves, retain full
  text with wrapping, and place labels outward from the radial graph.
- Right-align the existing park and enterprise filter toolbars and use `检索`.
- Update `SPEC.md` and `readme.md` for these display behaviors.

## Out Of Scope And Forbidden Changes

- No backend, API, graph facts/topology, governance, permission, audit, or
  state-machine changes; no architecture change.
- No relabeling of other graph types or renaming of the existing graph entry.
- Preserve filtering, pagination, reset, export, node details, fullscreen,
  and image download behavior; keep local services stopped after verification.
- No enterprise IAM, self-developed LLM gateway, new AI service, reverse
  pointers, or AI adoption bypasses.

## Acceptance And Verification

- Both teaching-standard leaf types show their full label before hovering;
  long text wraps in the embedded, fullscreen, and export chart options.
- Park and enterprise controls use the existing responsive upper-right layout,
  with one `检索` button and working reset/export controls.
- Run existing affected component tests, TypeScript and scoped ESLint checks,
  and `git diff --check`; inspect graph rendering where tooling permits.
- This is a display correction within existing Console flows; no new high-risk
  P0 flow, dialog, or state label is introduced.

## Verification Evidence

- Existing park, teaching-standard list, teaching-standard knowledge-view, and
  capability task-subgraph tests: 4 files / 6 tests passed.
- `npm run typecheck`: passed.
- Scoped ESLint: 0 errors; 5 existing hook warnings in `CapabilityGraphView`.
  The normal config cannot load the existing missing
  `eslint-plugin-testing-library`; a temporary config retained the production
  Next.js/core-web-vitals/TypeScript presets and existing hook warning levels.
- ECharts SVG rendering used the production graph-option functions with four
  occupational domains and 16 long leaves across both leaf types. At
  850x760, 1120x900, and 1600x1100, all 50 text lines stayed within canvas
  bounds. The 850px rendering was also inspected as a PNG; full labels wrap
  outward from the graph with reserved margins.
- No live API/Console page was started. Local services remain stopped;
  verification used existing component tests and standalone ECharts rendering.
