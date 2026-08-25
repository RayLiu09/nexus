# Task Package: Web Table Preview Repair

## Source Context

- `ARCHITECT.md`: normalized documents are the only permitted downstream input and must retain locator lineage.
- `SPEC.md`: Asset Detail provides an original-content preview for normalized documents.
- `WORKFLOWS.md`: this is a bounded parser and console-rendering repair with focused verification.

## Goal

Render crawler HTML table content correctly in Asset Detail while retaining a valid, locator-aligned normalized Markdown document for knowledge processing.

## Scope

- Repair malformed pipe-table output from the Firecrawl/trafilatura HTML path when a GFM header separator is absent.
- Keep source blocks and Markdown character ranges derived from the repaired normalized representation.
- Make wide preview tables horizontally scrollable without changing asset APIs or catalog schemas.
- Reprocess the reported asset as an auditable replacement version.

## Out Of Scope

- Changing raw crawler content.
- Rewriting historical normalized references in place.
- Adding generic asset catalog fields.

## Forbidden Changes

- Do not introduce raw content as a governance input.
- Do not alter the knowledge or asset state contracts.
- Do not add a new external API.

## Deliverables

- HTML Markdown repair with focused tests.
- Preview table container and focused component test coverage where practical.
- Reprocess evidence for asset `34d13426-2382-4f9b-bfb0-c7128c90fcd1`.

## Acceptance

- A malformed table with a header and data rows receives exactly one valid GFM separator row.
- A valid GFM table is unchanged.
- The reported asset's replacement normalized payload renders its school list as a table.
- Existing targeted pipeline and console checks pass.
