# Task Package: Evidence Graph Build Diagnostics

## Task name

Expose Evidence Graph build diagnostics in Console.

## Source context

- `docs/evidence_graph_contextual_unit_design.md`: contextual units,
  multi-chunk evidence, and granularity governance write build diagnostics into
  `quality_summary`.
- `nexus-console/app/assets/[assetId]/_components/EvidenceGraphView.tsx`:
  Evidence Graph page already loads `KnowledgeGraphBuild.quality_summary`.

## Goal

Make Evidence Graph build quality observable from the Console so operators can
understand candidate selection, unit grouping, extraction, persistence, and
governance outcomes without reading raw JSON first.

## Scope

- Add a compact "构建诊断" entry on the Evidence Graph toolbar.
- Render `quality_summary` in a Drawer with structured sections:
  candidate selection, unit grouping, extraction, persist/governance, errors,
  recoveries, and raw JSON fallback.
- Keep compatibility with old builds whose summaries lack new fields.
- Run Console typecheck.

## Out of scope

- New backend APIs.
- New database fields.
- Changing graph layout, filtering, or rebuild behavior.
- Component test harness setup.

## Acceptance

- Succeeded, running, failed, and old builds can open diagnostics without
  frontend exceptions.
- Newly added governance metrics are visible when present.
- `npm run typecheck` passes.
