# Task Package: Citation card and drawer polish

Date: 2026-11-05. Status: implemented and verified; human Frontend UX Gate pending before merge. Single agent.

## Context And Goal

Follow ARCHITECT.md's existing authenticated citation preview, SPEC.md's readable
source presentation, Prototype v2.2 section 6.12, and WORKFLOWS.md Frontend UX Gate.
Apply the user's latest presentation requirements to the intelligent-search Chatbot.

## Scope And Frozen Boundaries

- Citation card excerpts occupy at most six lines and cards shrink to their content.
- Remove the drawer's platform asset link and the composer's page-history caption.
- Preserve full drawer content preview and safe HTTP(S) external links, labelled
  “打开网络资源”, with a new tab and noopener/noreferrer.
- Follow-up: job-list/detail citations (`query_market_jobs`, `get_market_job`)
  omit this link even when a source URL exists. Web-search citations retain it.
  Verify both job tools and the existing external-web positive case.
- Allowed: Chat.module.css, ChatMessage.tsx, QueryPlayground.tsx, focused query UI
  tests, browser evidence, product/page documentation and review evidence.
- No backend/API/schema/permission/history changes, new dependencies, credential
  changes, governance edits, commit or push. Preserve unrelated working changes.
- All root AGENTS.md architecture prohibitions remain in force; no IAM, gateway,
  reverse-pointer model changes or AI governance bypass.

## Deliverables And Acceptance

- Bounded CSS specificity fix, UI changes and documentation.
- Unit coverage for retained external links and removed asset links.
- Browser verification at desktop and 390px: long excerpts actually clamp to six
  lines, short adjacent cards do not stretch, no horizontal overflow, existing
  preview and keyboard flows work.
- Relevant query unit tests, TypeScript and targeted lint pass. Record evidence
  for Frontend UX Gate; human approval is required before merge.

## Delivery Evidence

Query frontend 56 passed; TypeScript and targeted lint passed. Browser regression
10 passed, including six-line computed geometry, natural short-card height, full
preview and safe external links at desktop/390px. See
[review evidence](../review/query_latency_optimization_review.md).
