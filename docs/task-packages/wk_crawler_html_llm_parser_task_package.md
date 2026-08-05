# Task Package: Crawler HTML Deterministic Parser

## Source Context

- `docs/crawler_design_v1.0.md`: Firecrawl HTML/PDF/Markdown enters Pipeline A; crawler has no JSON package scenario; policy/report section context needs stable locator fields.
- `ARCHITECT.md`: Pipeline routing is frozen in `Job.payload.pipeline_type`; governance input must be normalized assets, not Firecrawl raw output.
- User decision: Firecrawl HTML entering parse is already `onlyMainContent` filtered; do not use LLM for HTML parsing. Use `trafilatura` as the primary extraction engine plus NEXUS-owned deterministic Markdown block, section, and locator builders. Locator may point to parsed Markdown rather than original DOM; PDF stays on MinerU.

## Goal

Make Firecrawl HTML assets robust for policy/report/regional-data retrieval by converting main-content HTML into faithful Markdown plus structured blocks, sections, retrieval hints, noise evidence, and Markdown range locators before normalize/governance/index without using LLM calls in the parse stage.

## Scope

- Add a crawler HTML deterministic parser using `trafilatura` as the primary extractor.
- Route only `crawler + firecrawl_document + text/html + web_document` through this parser in Pipeline A parse.
- Keep `text/markdown` on the lightweight Markdown adapter and `application/pdf` on MinerU.
- Preserve block `source_url`, `section_id`, `locator_type=markdown_range`, and `md_char_range` into semantic repack and chunk locators.
- Update focused tests and crawler/root contracts.

## Out Of Scope

- No LLM-based HTML parse path.
- No LLM fallback or optional LLM enhancement for crawler HTML parse.
- No DOM-layout locator for crawler HTML assets.
- No new persistent section table.
- No change to general uploaded HTML parsing or PDF/MinerU behavior.
- No crawler JSON package scenario.

## Forbidden Changes

- Do not introduce crawler HTML parse-time LiteLLM calls.
- Do not log large HTML/Markdown body content or model credentials.
- Do not introduce a new LLM gateway; use existing LiteLLM.
- Do not add master-data reverse pointers.

## Acceptance

- Firecrawl HTML parse does not require an LLM client or model alias.
- Successful HTML parse creates a `firecrawl-web-document-v1` parse artifact with `parser_backend=trafilatura-html-main-content-v1`, Markdown body, deterministic blocks, sections, retrieval hints, and quality metrics.
- Blocks and chunks preserve `markdown_range` locators with source URL and section ID.
- If extracted Markdown lacks H1, parse inserts a synthetic title heading and generates block/section Markdown ranges against the final Markdown.
- Focused pipeline, worker, config, crawler client, and crawler API tests pass.
