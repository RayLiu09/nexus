# Task Package: Retrieval Recall Console Conversation UX

## Source Context

- `SPEC.md`: Console P1 includes retrieval testing, and search/QA results must preserve source traceability.
- `docs/knowledge_retrieval_result_enhancement_v1.0.md`: Console retrieval conversations display intent analysis, retrieval plans, and multi-step execution progress as user-visible auxiliary analysis.
- `docs/retrieval_recall_v1_implementation_plan.md`: v1.0 retrieval flow is intent recognition -> query transformation -> parallel retrieval -> context pack -> Markdown summary.
- `docs/task-packages/wk_retrieval_recall_v1_orc08_task_package.md`: `/internal/v1/knowledge-retrieval/query` returns the full context pack for Console use, but did not include Console UI implementation.
- `nexus-console/app/search`: existing retrieval verification page and Console API proxy.

## Goal

Optimize the Console retrieval verification page into a conversation-window experience that makes retrieval/query execution observable and interactive, similar to a multi-agent task execution process.

## Scope

- Update `nexus-console/app/search/page.tsx` page copy.
- Refactor `nexus-console/app/search/_components/SearchPlayground.tsx` into a chat-style retrieval verification workbench.
- Preserve existing `/api/search`, `/api/qa`, and `/api/knowledge-retrieval` calls.
- Display user messages, execution steps, step details/results, intent analysis, retrieval plan, Markdown response, source refs, and clarification suggestions.
- Add lightweight client-side simulated running steps while the non-SSE API request is pending.

## Out Of Scope

- Backend API changes.
- SSE or realtime server push.
- New retrieval data sources.
- Permission filtering changes.
- Search/QA contract changes.
- Database migrations.

## Forbidden Changes

- Do not expose Console control-plane APIs as external business APIs.
- Do not introduce RAGFlow or Evidence Graph as retrieval sources.
- Do not bypass existing Next.js API proxy boundaries.
- Do not persist query plaintext, answer content, prompt text, source content, or API keys.
- Do not modify unrelated asset detail or API files.

## Deliverables

- Conversation-style retrieval verification UI.
- Interactive clarification/retry controls.
- Execution-step observability for intent recognition, query transformation, retrieval execution, and result generation.
- Typecheck/lint or equivalent verification evidence.

## Acceptance

- The `/search` page loads as a dialog-style workbench rather than a form/result page.
- Submitting a query creates a user message and an assistant execution message.
- During execution, users can see step progress.
- Completed v1.0 retrieval responses show intent analysis, retrieval plan, retrieval results, Markdown answer, and source refs.
- Low-confidence responses show clarification guidance and clickable refinement suggestions.
- Legacy semantic search and QA modes still work through the same conversation shell.
