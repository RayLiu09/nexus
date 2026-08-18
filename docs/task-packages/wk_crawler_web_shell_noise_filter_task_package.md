# Task Package: Crawler Web Shell Noise Filter

## Goal

Prevent crawler-acquired GitHub file display pages from entering normalization,
AI governance, or knowledge indexing when the extracted body is only the
GitHub session/navigation shell rather than the requested file content.

## Source Context

- `ARCHITECT.md`: Pipeline A keeps `assetize` and `normalize` separate; its
  required audit trail includes `PIPELINE_FAILED`.
- `SPEC.md`: Firecrawl HTML uses deterministic `trafilatura` extraction and
  every job failure must be locatable.

## Scope

- Pipeline A Firecrawl HTML parse-stage quality gate.
- Non-retryable Worker outcome and existing failure audit path.
- Focused Firecrawl pipeline tests.

## Out Of Scope

- New tables, migrations, APIs, crawler plans, or automatic deletion of raw
  objects.
- Broad domain or URL-blocking rules for GitHub.

## Guardrail

Reject only the conjunction of a GitHub `/{owner}/{repo}/blob/` display URL,
GitHub session-shell marker text, and an extracted two-block document. A
normal GitHub document with substantive extracted content must remain allowed.

## Acceptance

- The rejected job is terminal `failed`, carries
  `crawler_web_shell_detected`, and produces no parse artifact or normalized
  reference.
- A normal Firecrawl HTML page continues through the existing parse path.
- Run:

```bash
cd nexus-app
uv run pytest tests/test_pipeline_firecrawl_web_document.py
```
