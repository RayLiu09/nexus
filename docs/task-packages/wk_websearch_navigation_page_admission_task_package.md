# Task Package: WebSearch Navigation Page Admission Gate

## Source Context

- `AGENTS.md`: only usable normalized evidence may progress through
  governance; `available` requires no blocking rule and index admission.
- `ARCHITECT.md`: crawler acquisition must retain a traceable failure path but
  must not turn search/navigation noise into governed assets.
- `WORKFLOWS.md`: crawler-admission and lifecycle behavior needs focused
  regression evidence and auditability.

## Goal

Prevent WebSearch policy-navigation and search-result aggregation pages from
being persisted as raw objects, submitted to Pipeline A, or admitted to the
asset catalog.  A navigation page containing many policy snippets is not a
single policy document.

## Scope

- The existing `evaluate_websearch_item` crawler admission gate.
- WebSearch admission and Open external-search ingestion regression tests.
- Archive the identified already-admitted navigation asset through the
  supported lifecycle operation, retaining lineage and an audit record.

## Out Of Scope

- Changes to policy-classification prompts, governance schemas, database
  models, public APIs, or crawler query relevance ranking.
- Deleting raw evidence or changing genuine policy-detail-page admission.

## Guardrail

Reject only when independent search-navigation signals agree: a recognized
search route/query or explicit search-page title, together with a body result
count such as `相关结果177条`.  A policy detail page is not rejected merely
because it mentions search, policies, or a result count in ordinary prose.

## Deliverables

- Stable rejection reason: `navigation_search_results`.
- Focused tests proving no data source, raw object, or job is created for the
  reported page shape, while a Beijing policy detail page remains eligible.
- Auditable archival evidence for asset
  `b12b4e00-7b75-46ea-913b-99ba69db61e2`.

## Acceptance

Run:

```bash
cd nexus-app
uv run pytest tests/test_websearch_quality_gate.py tests/test_open_search_ingest.py
```

- The reported URL/content topology returns `navigation_search_results`.
- Filtered pages create neither raw objects nor jobs.
- The archived historical asset is excluded from current asset and retrieval
  reads while its lineage and audit record remain available.
