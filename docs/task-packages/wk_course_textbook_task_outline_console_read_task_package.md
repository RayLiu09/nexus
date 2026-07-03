# Task Package: Task Outline Internal API And Console Read View

## Task name

Task Outline asset-detail read view.

## Source context

- `docs/course_textbook_knowledge_processing_design.md`: Task Outline should be
  visible for task-operation textbooks and support source locator jumps.
- `docs/course_textbook_knowledge_processing_implementation_plan.md`: Package E
  owns internal API, Console proxy, tree view, source locator action, and empty
  states.
- Package A-D task packages: persistence, extraction, chunk projection, and
  Evidence Graph admission control are already implemented.
- `SPEC.md`: Console APIs are internal control-plane APIs; externally consumed
  business APIs belong in `nexus-api` under `/v1`.

## Goal

Expose persisted Task Outline profile/nodes through an internal read API and add
a Console asset-detail Task Outline tab for document normalized refs.

## Scope

- Internal read endpoint for `normalized_ref_id -> task outline profile/nodes`.
- Console proxy route.
- Console TypeScript types and fetch helper.
- Asset detail document knowledge view tab.
- Read-only Task Outline tree component with clear empty states.

## Out of scope

- Manual node editing.
- Outline rebuild submission.
- Public/open API.
- Index stale handling.
- Evidence Graph UI warning.
- Full source preview integration beyond displaying locator/source block
  evidence already returned by the API.

## Forbidden changes

- Do not expose this as a business-facing `/v1` API.
- Do not bypass existing normalized-ref ownership and traceability.
- Do not add a NEXUS AI gateway management page.
- Do not add task-specific chunk tables.
- Do not edit unrelated asset-detail pages.

## Deliverables

- Internal API.
- Console proxy/fetch/types.
- Read-only Console tab/component.
- Tests or targeted verification.

## Acceptance

- API returns profile, nodes, and chunk projection summary for a normalized ref.
- API returns a stable empty response when no outline exists.
- Console can show a Task Outline tab for document refs.
- Empty states distinguish no normalized ref, no Task Outline built, and empty
  node tree.
- Node rows show title/content summary, node type, source block ids, and locator
  page range when available.

## Review Gates

- API Contract Gate for the internal API shape.
- Frontend UX Gate before merge.

## Verification

```bash
cd nexus-app
uv run pytest tests/task_outline
```

```bash
cd nexus-console
npm run lint
```

