# Task Package: Crawler Web Shell Noise Filter

## Goal

Prevent crawler-acquired GitHub file display pages from ever becoming raw
objects or pipeline jobs. GitHub `/{owner}/{repo}/blob/` URLs can resolve to
two kinds of noise instead of a readable document:

- **session shell** — JavaScript not rendered, leaving only the login/session
  notice (`github_blob_page_shell`);
- **source-code file viewer** — raw code rather than a rendered document
  (`github_blob_source_file`).

Both are rejected at crawler admission, before any job is submitted.

## Source Context

- `ARCHITECT.md`: Pipeline A keeps `assetize` and `normalize` separate; its
  required audit trail includes `PIPELINE_FAILED`.
- `SPEC.md`: Firecrawl HTML uses deterministic `trafilatura` extraction and
  every job failure must be locatable.

## Scope

- Crawler admission quality gate (`evaluate_snapshot` in
  `crawler/quality_gate.py`), which runs before `_ingest_firecrawl_snapshots`
  creates the batch, raw objects, and jobs.
- Parse-stage backstop (`_web_document_noise_evidence` in `pipeline/stages.py`)
  remains for the session-shell case as defense in depth.

## Out Of Scope

- New tables, migrations, APIs, crawler plans, or automatic deletion of raw
  objects.
- Broad domain or URL-blocking rules for GitHub.

## Guardrail

Reject only a GitHub `/{owner}/{repo}/blob/` display URL whose body matches one
of the two shell signatures above. A normal GitHub document with substantive
extracted content must remain allowed.

## Acceptance

- The filtered snapshot is recorded in the run `filter_reasons` and `failures`
  and never enters `accepted_snapshots`, so no raw object or job is created.
- A normal Firecrawl HTML page continues through the existing parse path.
- Run:

```bash
cd nexus-app
uv run pytest tests/test_websearch_quality_gate.py tests/test_pipeline_firecrawl_web_document.py
```
