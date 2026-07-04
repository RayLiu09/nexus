# Task Package: Evidence Graph Granularity Governance

## Task name

Strengthen deterministic canonicalization, weak-fact filtering, and duplicate
evidence accounting for Evidence Graph persistence.

## Source context

- `docs/evidence_graph_contextual_unit_design.md`: Stage 3 calls for graph
  granularity governance after contextual extraction units and multi-chunk
  evidence persistence.
- `nexus_app.evidence_graph.persist`: current persistence already merges exact
  duplicate fact keys and writes evidence-bound graph rows.

## Goal

Reduce noisy or redundant graph rows after extraction without changing the
database schema or weakening chunk-level evidence traceability.

## Scope

- Enhance deterministic entity, predicate, and literal canonicalization in
  `nexus-app/nexus_app/evidence_graph/persist.py`.
- Filter weak fact candidates before graph rows are written.
- Track duplicate evidence rows and canonicalization/weak-filter counters in
  `quality_summary`.
- Add focused persistence tests.
- Update the contextual unit design document with the Stage 3 implementation
  status.

## Out of scope

- LLM-based canonicalization.
- New graph tables or migrations.
- Console overview/focused graph redesign.
- Cross-build or cross-asset graph merge.

## Acceptance

- Equivalent metric literals such as `2.9%`, `2.9％`, and `2.9 %` merge into
  one fact.
- Equivalent predicates such as `发布` / `印发` / `出台` merge into one relation.
- Weak `MENTIONS` facts with poor semantic value are rejected and counted.
- Duplicate evidence rows from overlap windows are skipped and counted.
- Existing Evidence Graph focused tests pass.
