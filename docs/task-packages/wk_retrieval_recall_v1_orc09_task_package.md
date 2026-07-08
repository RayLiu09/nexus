# Task Package: ORC-09 Console Retrieval Recall UI

## Source Context

- `docs/retrieval_recall_v1_implementation_plan.md`: ORC-09 upgrades the Console search page into a multi-step retrieval/recall conversation view.
- `nexus-api` ORC-08: internal APIs `POST /internal/v1/knowledge-retrieval/query` and `/plans` are available.
- `nexus-console/app/search`: current search/QA playground using same-origin route handlers.
- `nexus-console/lib/api/proxy`: server-side proxy for `/internal/v1/*` with JWT from httpOnly cookie.

## Goal

Add a first Console UI for v1.0 retrieval/recall orchestration so users can see the final Markdown result, intent analysis, retrieval plan, step status, and source refs from one search page.

## Scope

- Add same-origin route handler for `POST /api/knowledge-retrieval`.
- Add TypeScript wire types for retrieval context packs.
- Extend `SearchPlayground` with a `召回编排` mode.
- Render:
  - Markdown result or clarification prompt.
  - Multi-step status timeline.
  - Intent analysis panel.
  - Retrieval plan panel.
  - Source refs summary.

## Out Of Scope

- SSE or live event streaming.
- Dedicated new page or navigation item.
- API contract changes.
- Backend retrieval implementation.
- Permission filtering; v1.0 keeps `access_scope = all_assets`.
- Productized audit views.

## Forbidden Changes

- Do not expose API caller keys to the browser.
- Do not call `/internal/v1/*` directly from client components.
- Do not add a NEXUS AI gateway management page.
- Do not introduce RAGFlow or Evidence Graph as retrieval/recall sources.
- Do not change `/api/search`, `/api/qa`, `/open/v1/search`, or `/open/v1/qa` behavior.
- Do not touch unrelated knowledge outline backend changes.

## Deliverables

- `nexus-console/app/api/knowledge-retrieval/route.ts`
- `nexus-console/app/search/_lib/searchTypes.ts`
- `nexus-console/app/search/_components/SearchPlayground.tsx`

## Acceptance

- Search page includes a `召回编排` mode.
- Query mode calls `/api/knowledge-retrieval` and renders backend Markdown.
- Low-confidence responses render clarification text and do not show fake final answers.
- UI displays intent analysis and retrieval plan as auxiliary analysis.
- UI displays each step status and sub-query counts/errors.
- UI displays source refs without leaking API keys, Prompt text, or caller keys.
