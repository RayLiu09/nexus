# Task Package: Crawler DeepSeek Search

## Goal

Add DeepSeek as a selectable Crawler WebSearch provider while preserving existing Custom plans.

## Scope

- Add server-only `BASE_URL_DEEPSEEK` and `API_KEY_DEEPSEEK` settings.
- Add `websearch/deepseek` plans and a Search API client with `need_content=true`.
- Keep `rerank_score` for diagnostics without filtering; policy and regulatory documents require `authority >= 3`.
- Reuse the existing raw-object, document normalization, governance, and audit path.
- Extend the Crawler Console provider selection and add focused tests.
- Default newly created WebSearch plans to DeepSeek while copied plans retain their provider.

## Boundaries

- No DeepSeek key in plans, responses, logs, audit, or frontend bundles.
- No summary-only document admission. No change to the real-time retrieval WebSearch path.
- No direct governance from Search JSON; Pipeline A still starts from the retained raw object.
- Existing `websearch/custom` plans and parsing remain compatible.

## Acceptance And Review

- Request uses `/v1/tools/search`, Bearer auth, and `need_content=true`.
- Low-score results remain eligible; specified formal document titles below authority 3 are filtered.
- Eligible content is admitted only after URL and content quality checks.
- API Contract, Pipeline / Architecture, and Permission / Audit gates review the plan identity,
  raw metadata, and redacted diagnostics before release.
