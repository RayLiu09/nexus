# Task Package: Query action reporting and duplicate calls

Date: 2026-11-05. Status: implementation and focused verification complete; human Review Gates pending before merge. Single agent.

## Problem And Goal

The Chongqing 2026 low-altitude policy/industry-chain query shows indistinguishable planning/document actions and empty actions displaying a cumulative source count. Make execution facts unambiguous and prevent identical successful/empty HTTP queries within a turn while retaining distinct keyword/filter queries and recovery from failures.

## Contract And Scope

- Keep existing query/SSE routes, budgets, permissions, Prompt persistence and ingestion policy.
- Distinguish initial planning, supplemental planning and evidence checking. Add a short human-readable, sanitized business-query summary to tool actions; never expose raw argument JSON, credentials or UUIDs.
- Report per-call source count, newly registered source count and explicitly named cumulative count separately. Empty nonaggregate calls have no sources and never inherit earlier citations (a zero-count aggregate can retain a valid statistics citation). Source registration returns only IDs actually associated with the current response.
- Reuse successful/empty results for identical tool+canonical JSON arguments within one turn, without another HTTP call or fake execution step. Failed attempts can retry; distinct scopes remain distinct. Record reuse count in final audit and provide the cached result to subsequent model context.
- Allowed: public_query_runtime/sources and their tests, ChatMessage and focused tests, existing query browser fixtures, relevant SPEC/architecture/prototype/readme and review evidence. Preserve unrelated workspace changes.

## Verification And Review

Backend tests cover empty-after-success, overlapping source registration, per-call vs cumulative counts, identical/different arguments and failure retry. Frontend tests cover empty legacy cumulative output and readable action summaries. Run appropriate SSE regressions, TypeScript and browser process fixture. Replay the user question locally with ingestion disabled and record observed behavior. API Contract, Permission/Audit, Semantic Retrieval and Frontend UX review evidence is required before merge; no schema migration, commit or push in this task.

Verification complete: backend 50 passed, query UI 34 passed, TypeScript passed, Playwright 6 passed, targeted ChatMessage lint clean, diff whitespace check passed. Actual user question completed with every empty action reporting zero per-call sources; desktop and 390px actual-event replay confirmed readable query conditions, two empty actions and no horizontal overflow. See [review evidence](../review/query_action_reporting_fix_review.md), including the existing 404 knowledge-outline limitation and 40-citation cap.
