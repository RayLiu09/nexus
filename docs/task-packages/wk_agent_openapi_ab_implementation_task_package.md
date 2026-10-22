# Task Package: Agent Open API A/B Consumption Tools

## Source And Authorization

- User authorizes implementation of A/B gaps in
  `docs/agent_openapi_gap_analysis_2026-10-22.md` and an OpenAPI-generated
  function-tools catalog; C/change-feed interfaces are explicitly excluded.
- Read `ARCHITECT.md`, `SPEC.md`, Prototype v2.2, `WORKFLOWS.md`, and the
  preceding analysis, record-graph, and asset-catalog task packages.

## Bounded Implementation Slices

1. Public read foundation and business records: shared available/current-ref
   selection and audit; raw-job search/detail/aggregation; parks/enterprises;
   teaching standards/courses; textbooks; professional-introduction documents.
2. Document and evidence consumption: catalog filters, scoped multi-KB search,
   bounded sections, read-only outlines/node contexts/graphs, batch evidence,
   entity candidates, and resource discovery.
3. External tooling contract: derive Responses and Chat Completions function
   definitions plus HTTP bindings from public OpenAPI; deterministic checked-in
   artifacts, typed new responses, contract/security/audit tests, docs.

Single-agent sequential work. Existing public routes remain compatible; no
parallel-agent contract is needed. File ownership: `nexus-api` public routes,
public schemas/helpers/tool generator/tests, narrowly extended app catalog
schema, generator script, generated artifacts, and contract/review documents.

## Frozen Boundaries

- Canonical prefix remains `/open/v1` in `nexus-api`.
- Document reads require an available version and its latest generated ref;
  document projections also require their latest official classification.
- Business tables keep their existing record boundaries; raw recruitment
  records never become governance inputs. No migrations or production writes.
- Standards require an active library plus the available document boundary.
- Only existing/generated graph or outline data is returned. No implicit build,
  rebuild, promotion, arbitrary SQL/code, or new knowledge production pipeline.
- Missing fields remain missing. No numerical salary, skill-frequency, city,
  or nationwide-statistics claims without stored source facts.
- Existing API Caller `open:*` policy is retained; do not claim org filtering.
- All new consumption reads authenticate and audit caller, bounded query
  summary/counts and trace ID. Batch reads validate every item's visibility.
- Legacy structured major-profile routes remain compatible but are deprecated;
  document tools use current identity metadata, including audited overrides.
- Generated tools include only public operations; headers/credentials stay out
  of model arguments. Streaming and deprecated operations are excluded.
  External-search tools explicitly default auto_ingest to false in their tool
  schema; HTTP side effects remain described and caller-controlled.

## Acceptance And Review Evidence

- A/B coverage matrix links each gap to implemented route or reused capability.
- Tests cover auth, current-ref/available-only reads, inactive standards,
  schema errors, deterministic pagination, source/aggregate consistency,
  no-build reads, mixed-visible evidence, retrieval scope, and audit.
- Tool generation resolves local schema refs, preserves path/query/body
  placement and repeated query arrays, yields stable unique names, and can be
  regenerated without importing lifespan or contacting external services.
- Run focused tests, then relevant API regression suite and artifact drift
  checks. Update root contracts and provide API/Permission/Audit/Retrieval
  Review Gate evidence without claiming human approval.
- C APIs, internal controls, unrelated untracked files, service startup,
  deployment, commits, and pushing are outside this implementation task.

## Delivered

- Three sequential slices implemented: 25 new public operations plus catalog,
  search, ability-analysis and training-plan enhancements.
- Public OpenAPI generates 55 function tools with Responses/Chat Completions
  formats, HTTP bindings and a readable list; artifact drift check passes.
- Comprehensive regression: 170 passed; final targeted regression: 20 passed,
  including the additional missing-payload batch case.
- API coverage/parameters/examples: `docs/api/public_agent_data_api.md`.
- Gate evidence: `docs/review/wk_agent_openapi_ab_review_evidence.md`.
- No C routes, migrations, production writes or service startup. Human merge
  review remains governed by WORKFLOWS.md; this record does not assert approval.
