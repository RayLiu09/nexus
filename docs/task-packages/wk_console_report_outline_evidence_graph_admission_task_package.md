# Task Package: Console Report Outline Evidence Graph Admission

## Goal

Hide the Console Evidence Graph entry for `industry_report` and
`sector_report` document assets. These classifications already expose a
chapter-structured knowledge-outline experience, so a second graph-construction
entry is not part of the operator workflow.

## Scope

- Add a Console-only admission helper for the two official classification codes.
- Pass the resolved official classification into `DocumentKnowledgeView`.
- Hide the Evidence Graph segmented option for those classifications and reset
  the active view to `RAG知识块` if the classification changes while viewing it.
- Add focused unit tests for the admission helper.

## Out Of Scope

- Evidence Graph API, worker, persistence, model, prompt, or extraction changes.
- Deleting, cancelling, or modifying existing graph builds.
- Changes to the report knowledge-outline rendering itself.

## Forbidden Changes

- Do not infer admission from raw source files, MinerU output, or client-only
  content heuristics.
- Do not expose Console admission rules through external `/open/v1` APIs.
- Do not change the `knowledge_graph_*` data model.

## Acceptance

- Asset Detail does not show an Evidence Graph entry when the resolved
  classification is `industry_report` or `sector_report`.
- All other graph-admitted document classifications retain their existing entry.
- A stale selected Evidence Graph view falls back to `RAG知识块` when admission
  becomes unavailable.

## Verification

```bash
cd nexus-console
npm run test -- lib/evidenceGraphAdmission.test.ts
npm run typecheck
```
