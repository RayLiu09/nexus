# Task Package: Crawler WebSearch Custom

## Goal

Add `WebSearch` as a managed Crawler data source. Its only supported version is
`custom`, backed by Doubao Search Custom API. Search results enter Pipeline A
only after full response documents are stored as `raw_object` payloads in MinIO.

## Scope

- Add immutable connector/version and WebSearch search-policy snapshots to
  Crawler plans and runs.
- Add a Custom API client, response compatibility parser, and synchronous
  WebSearch runner.
- Store each accepted Markdown result as a full raw JSON object in MinIO, then
  submit it with `Job.payload.pipeline_type=document`.
- Add a Markdown document parse route and lightweight normalized lineage.
- Extend the internal Crawler API and Console plan flow.
- Add the single WebSearch quick-start query:
  `电子商务产业(跨境电商和直播电商)政策和市场概况`.

## Frozen Contract

- `connector_type=websearch`; `connector_version=custom`. No other WebSearch
  version is selectable or supported in P0.
- Requests are `SearchType=web`, `ContentFormats=markdown`, `NeedContent=true`,
  `NeedUrl=true`, `Industry=gov`, and `QueryRewrite=true`.
- Generic plans accept one query only. A query containing whitespace, `,`/`，`,
  or `;`/`；` is invalid. Validate in Console and backend.
- Result count is 10 through 50. Time presets are 3 months, 6 months, 1 year,
  2 years, 3 years, and 5 years; each run freezes an actual date range.
- Do not add application-side QPS limiting. Classify upstream HTTP/API rate-limit
  errors and stop outstanding run queries after a rate-limit response.
- `Content` and fallback `Summary` are stored only in MinIO raw-object content.
  Never copy content, summary, snippet, or the complete upstream response into
  audit payloads, run summary, or normalized lineage.
- `normalized_asset_ref.lineage` stores only IDs, checksum, source URL, provider
  trace IDs, content format/source, and plan/run relation.
- Do not alter request-scoped Firecrawl Query Router fallback behavior.

## Non-Goals

- No image search, `web_summary`, Global version, TOP AK/SK authentication,
  provider-side result throttling, or new scheduler/MQ dependencies.
- No content display in Crawler run history.

## Reliability Follow-up: WebSearch Admission

Source context: the crawler design requires a quality gate before a result
becomes a `raw_object`; run success must not conceal semantically unusable
results.

Scope:

- Apply a WebSearch-only admission gate before batch/raw creation.
- Record count-only `accepted`, `filtered`, and per-reason diagnostics in the
  run summary. Do not retain result content in the run summary.
- Use the upstream page title for WebSearch assetization.
- Keep WebSearch complete content in MinIO only; metadata may retain a bounded
  non-body summary but not a derived `content_snippet`.
- Use a stable, asset-level identity derived from the normalized source URL and
  a separate content fingerprint derived from normalized title + Markdown body.
  Batch/run/request identifiers, raw JSON serialization, MIME type, and other
  transport metadata must not affect either identity. An unchanged fingerprint
  reuses the existing asset version and skips parse, normalize, governance, and
  indexing; changed content at the same URL creates a new version of the same
  asset.
- Provide an operator cleanup/replay procedure for results admitted before the
  quality gate existed.

Acceptance:

- Low-rank, home/category, too-short, and insufficient-query-coverage results
  create neither raw objects nor jobs and are visible through `filter_reasons`.
- A run with filtered results is `partial_failed` when it also submitted work,
  and `failed` when no result passed admission.
- WebSearch asset titles equal the upstream `title` metadata.
- Re-running the same upstream URL and Markdown body creates no additional
  asset version or downstream processing chain, even if the Crawler run and
  provider request identifiers differ.

## Required Review Gates

- Data Model Gate
- API Contract Gate
- Pipeline / Architecture Gate
- Permission And Audit Gate
