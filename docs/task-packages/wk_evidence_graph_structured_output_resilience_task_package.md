# Task Package: Evidence Graph Structured Output Resilience

## Goal

Make Evidence Graph body extraction resilient to malformed model responses by
using LiteLLM JSON Schema structured output, one bounded format-repair attempt,
and safe per-attempt diagnostics.

## Scope

- Apply a strict top-level JSON Schema response format for graph candidates.
- Fall back to `json_object` only when a provider rejects `json_schema` as an
  unsupported request parameter.
- Retry once when the response cannot be parsed as candidates or all candidates
  fail schema validation.
- Persist only model alias, request correlation, input hash, response shape,
  attempt and outcome in `knowledge_graph_build.quality_summary`.
- Add focused extractor and processor tests.

## Out Of Scope

- Changes to public APIs, graph tables, asset/version state, governance rules,
  graph profile selection, or existing graph builds.
- Storing raw model responses, raw source content, credentials, or L3/L4
  plaintext in database rows or logs.

## Acceptance

- The normal request carries a strict `json_schema` response format requiring
  a top-level `candidates` array.
- An unsupported provider falls back once to `json_object` without an unbounded
  retry loop.
- A malformed or wholly schema-invalid response receives one repair attempt.
- Build diagnostics retain safe attempt summaries for both successful and
  failed extraction paths.
- Evidence remains bound to existing `knowledge_chunk` rows.

## Review Gate

AI Governance Gate: the human reviewer must confirm LiteLLM remains the only
model gateway, output is schema validated before persistence, no source/model
body is persisted in diagnostics, and the bounded retry cannot affect official
governance results.

## Verification

```bash
cd nexus-app
uv run pytest tests/test_evidence_graph_extractors.py tests/test_evidence_graph_processor.py
```
