# Task Package: Agent Open API Data Consumption Gap Analysis

## Source Context

- User request: analyze missing Open API tools for Agent applications, limited
  to asset types currently visible in Asset Center.
- `ARCHITECT.md`: business Asset Center, normalized references, read-only public
  graph adapters, and consumption lineage boundaries.
- `SPEC.md`: public API groups and current business-view semantics.
- Prototype v2.2: current Asset Center entries and document/record interactions.
- `WORKFLOWS.md`: bounded task packages and evidence for non-trivial work.
- Existing Open API, record graph, catalog filtering, and major-profile
  document retirement task packages.

## Goal

Produce a source-grounded coverage matrix and prioritized tool/API proposals
for external Agent data consumption.

## Scope

- Read Asset Center navigation, actual page data sources, public route
  registrations, schemas, and internal read capabilities.
- Document existing capabilities, gaps, data-source drift, proposed routes,
  Agent inputs/outputs, and acceptance scenarios.
- Deliver `docs/agent_openapi_gap_analysis_2026-10-22.md`.

## Out Of Scope And Forbidden Changes

- No runtime code, API contracts, migrations, production data, permission
  policy, or frontend behavior changes.
- No implementation or promotion of proposals into approved product scope.
- No hidden education-policy, course-standard, certificate, or user-behavior
  entries added to scope.
- No new IAM, gateway, governance service, graph production pipeline,
  arbitrary SQL/code tool, or reverse pointers.
- No treating raw recruitment records as normalized governance inputs or
  generated graph facts as new official business facts.

## Verification And Acceptance

- Check all 15 currently visible resource entries against page data sources
  and registered public routes.
- Distinguish existing APIs, parameter enhancements, and proposed new APIs.
- Identify raw-job and retired major-profile projection mismatches.
- Preserve document available-only semantics and record-domain boundaries.
- Mark verification as static source inspection; do not claim live endpoint
  health, populated data, completed deployment, or human Review Gate approval.
- Subsequent implementation requires separate small task packages and the
  applicable API Contract, Permission/Audit, Version State, and Retrieval Gates.
