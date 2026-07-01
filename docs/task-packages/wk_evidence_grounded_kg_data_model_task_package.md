# Task Package: Evidence-grounded KG Data Model

## Source Context

- `docs/evidence_grounded_knowledge_graph_design.md`: Evidence-grounded KG must be built from NEXUS-owned `knowledge_chunk` rows and remain evidence-bound.
- `docs/evidence_grounded_kg_implementation_plan.md`: Task Package A requires graph tables, ORM models, Alembic migration, and a basic repository/service.
- `ARCHITECT.md`: `knowledge_chunk.normalized_ref_id` links chunks to `normalized_asset_ref`; external index backend ids are not stored on chunks.
- `AGENTS.md`: governance and knowledge processing must start from standardized assets, not raw files or MinerU raw output.

## Goal

Create the persistent data foundation for Evidence-grounded KG builds so later slices can add profile selection, extractors, merge/quality gates, internal APIs, and console views without changing the storage contract again.

## Scope

- `nexus-app/nexus_app/models.py`: add Evidence-grounded KG ORM models.
- `nexus-app/alembic/versions/`: add migration for the graph tables.
- `nexus-app/nexus_app/evidence_graph/`: add minimal service/repository functions for build lifecycle and latest-build lookup.
- `nexus-app/tests/`: add model/service tests.
- `docs/evidence_grounded_kg_implementation_plan.md`: implementation source remains the phase plan.

## Out Of Scope

- Graph profile config and candidate selection.
- LLM/rule extractors.
- Entity merge and graph quality gates.
- `/v1` or internal API endpoints.
- Console Evidence Graph rendering.
- Graph database backend selection.

## Forbidden Changes

- Do not modify Pipeline B `CapabilityGraphStaging` semantics.
- Do not store external index backend ids on `knowledge_chunk`.
- Do not construct graph rows from raw files, raw JSON, or MinerU raw output.
- Do not add professional/position/ability graph semantics to Evidence-grounded KG tables.
- Do not add enterprise IAM, RabbitMQ, Celery, or Redis as required dependencies.

## Deliverables

- Six graph tables:
  - `knowledge_graph_build`
  - `knowledge_graph_node`
  - `knowledge_graph_fact`
  - `knowledge_graph_edge`
  - `knowledge_graph_mention`
  - `knowledge_graph_evidence`
- ORM models aligned with the migration.
- Minimal service functions to create builds, query latest succeeded builds, and mark build status.
- Tests proving build/node/fact/edge/mention/evidence persistence and latest succeeded build lookup.

## Acceptance

- A test can create a `knowledge_graph_build` linked to `normalized_asset_ref`.
- A test can create node, fact, edge, mention, and evidence rows linked to the build and source `knowledge_chunk`.
- A test can query the latest succeeded build by `normalized_ref_id`.
- Duplicate `(graph_build_id, node_key)` is rejected.
- Existing relevant pipeline tests still pass.
