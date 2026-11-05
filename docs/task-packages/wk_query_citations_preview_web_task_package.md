# Task Package: Relevant citations, source preview and explicit web search

Date: 2026-11-05. Status: implementation and verification complete; human Review Gates pending before merge. Single agent.

## Goal And Scope

Fix unrelated catalog candidates and misleading all-candidate citations for the Chongqing low-altitude question; provide source-content preview in the citation drawer; add an explicit per-query DeepSeek web-search switch requesting 10 results alongside platform retrieval. Remove the static sentence promising automatic web fallback.

Allowed: public document topic predicate and isolated filtering tests; public-query runtime/source registry and focused tests; internal query request wiring; Console JSON/SSE proxies/hook/chat/preview and tests; existing preview APIs/components where reusable; architecture/spec/prototype/readme and review evidence. Preserve unrelated edits.

## Frozen Contract

- Internal query payload adds strict boolean `web_search`, default false. Off executes platform retrieval only; on also requests existing `search_web_search` with count=10 regardless of local success. Explicit local-only/asset scope, sensitive-outbound checks and deployment ingestion policy remain enforced and audited. External legacy query remains unchanged. No model-selected endpoint/secret or write tool.
- Distinguish candidate sources from final references; final visible references are only valid IDs actually cited in the answer. Preserve original IDs and record counts for audit. Dedupe the same evidence across overlapping filter queries; later evidence updates earlier metadata without losing anchors. Reserve capacity for up to 10 webpage sources so local candidates cannot suppress them.
- Preview actual normalized content through existing authenticated Console APIs, with loading/error/empty states, abort/stale-response protection, readable Markdown and no raw technical JSON/IDs. Platform asset links remain available. Web sources show acquired content/URL, never masquerade as governed assets.
- Read evidence for relevant candidate documents, not the first arbitrary metadata hits; preserve finite call/time budgets and all available/current-ref/permission gates. Fix topic SQL correlation with a cross-asset negative test.
- No new business-facing API, schema migration, permission widening, active Prompt overwrite, commit or push. User-visible copy does not promise web access while the switch is off.

## Acceptance

Topic isolation and citations/dedup/metadata-to-body tests; web flag contract off/on and 10-result request tests; preview loading/content/denied/stale tests; proxy/hook request propagation; appropriate API/SSE regressions, TypeScript and desktop/mobile browser validation. Real read-only original-question smoke with ingestion disabled. API Contract, Permission/Audit, Semantic Retrieval and Frontend UX Review Gate evidence before merge.


## Verification Evidence

131 API tests, 55 frontend tests, TypeScript and targeted ESLint passed. Final full browser regression: eight scenarios passed across desktop/mobile. Real original-question
runs: web off 30 candidates/5 cited sources; web on 40 candidates/8 cited sources,
10 actual DeepSeek results, no ingestion. Real authenticated body preview returned
29,052 characters and worked at 1440px/390px. See
[review evidence](../review/query_citations_preview_web_review.md) for limits and
human gates before merge. No commit, push or merge.
