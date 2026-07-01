# Task Package: Evidence-grounded KG Internal API

## Source Context

- `docs/evidence_grounded_kg_implementation_plan.md`: Task Package E requires build submit, build list/detail, node/edge/fact/evidence queries, latest graph lookup, and rebuild endpoint.
- `nexus-app/nexus_app/evidence_graph/`: previous slices provide data model, candidate selection, extractor schema, and persist service.
- `nexus-api/nexus_api/api/internal/capability_graph_staging.py`: local read-only graph preview API pattern.

## Goal

Expose Evidence-grounded KG data through internal console APIs so the Console can list builds, inspect graph rows, filter evidence by chunk, and preview latest graph state for a normalized ref.

## Scope

- `nexus-api/nexus_api/api/internal/evidence_graph.py`: internal API routes.
- `nexus-api/nexus_api/api/internal/__init__.py`: mount the router.
- `nexus-api/tests/`: API tests for list/detail/filter/latest/dry-run/rebuild/404.
- `docs/evidence_grounded_kg_implementation_plan.md`: mark Task Package E as started.

## Out Of Scope

- Console UI rendering.
- Running LLM extraction in API request handlers.
- Background worker orchestration for full graph builds.
- Public/open API exposure.

## Forbidden Changes

- Do not bypass `/internal/v1` JWT boundary.
- Do not expose Evidence Graph as a public API in this slice.
- Do not call raw files, raw JSON, or MinerU raw output.
- Do not mix Evidence Graph with Pipeline B capability graph staging.

## Deliverables

- `POST /internal/v1/knowledge-graphs/builds`
- `POST /internal/v1/knowledge-graphs/rebuild`
- `GET /internal/v1/knowledge-graphs/builds`
- `GET /internal/v1/knowledge-graphs/builds/{build_id}`
- `GET /internal/v1/knowledge-graphs/builds/{build_id}/nodes`
- `GET /internal/v1/knowledge-graphs/builds/{build_id}/edges`
- `GET /internal/v1/knowledge-graphs/builds/{build_id}/facts`
- `GET /internal/v1/knowledge-graphs/builds/{build_id}/evidence`
- `GET /internal/v1/normalized-refs/{ref_id}/knowledge-graph`

## Acceptance

- API tests cover pagination, filtering, 404 behavior, build status, and `chunk_id` evidence reverse lookup.
- Build submit supports `dry_run=true` candidate selection without creating a build.
- Non-dry-run submit creates a build envelope and candidate selection summary but does not run LLM extraction inline.
