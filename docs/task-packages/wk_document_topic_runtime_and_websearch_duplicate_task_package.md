# Task Package: Document Topic Runtime And WebSearch Duplicate Repair

## Source Context

- `AGENTS.md`: retain raw objects; keep parse, normalize, and assetize distinct; reprocess is auditable.
- `WORKFLOWS.md`: API Contract, Version State, and Frontend UX Review Gates.
- Asset `0d78d0c7-ceef-40cb-b0f9-14d2a0745295` has an entire article repeated in its retained WebSearch raw package.

## Goal

Make live document topic totals reflect the new API filter, present distinct colored topic chips, and remove whole-article duplication from future WebSearch parse output and the affected asset through reprocessing.

## Scope

- WebSearch Markdown parse deduplication only when a repeated article section is strongly evidenced.
- Focused parser and Console tests.
- Bring up current API/Console runtime and reprocess the identified asset via existing audited flow.

## Out Of Scope

- Changes to raw-object bytes, arbitrary paragraph deduplication, governance result edits, or new document classifications.

## Forbidden Changes

- Do not overwrite historical normalized payloads or silently mutate official governance state.
- Do not remove nonduplicate sections or repeated phrases that are legitimate content.

## Acceptance

- Current API recognizes the topic query parameter; the two totals diverge where data differs.
- Topic chips have distinct colors and preserve filter/pagination behavior.
- Duplicate whole-article input yields one article with correct block ranges; nonduplicate input remains unchanged.
- The target asset obtains a new normalized ref through reprocess, retaining the source version and audit trail.

## Verification Evidence

- API OpenAPI now lists `topic` on `/internal/v1/industry-policies`; the old API process had no such parameter and returned the unfiltered total for both chips.
- Shared database read-only totals after the restart: industry policy `857 / 374 / 298`, industry report `598 / 223 / 317`, sector report `295 / 225 / 64` (all / finance-commerce / low-altitude). These are live counts and can change as ingestion continues.
- Asset `0d78d0c7-ceef-40cb-b0f9-14d2a0745295`: retained WebSearch raw content contained two full copies of the article. Audited reprocess job `6e334cfb-a760-4d10-a247-fe3d4973c4de` succeeded; version 2 ref `31c41b09-4ae4-4ce2-8146-25dd02d2717d` has 11 blocks and one copy of the article, versus 20 blocks in retained version 1.
- Asset `f0cdeb49-16d2-47c6-8353-5cda683559c6`: audited reprocess job `ab51ab9d-f811-49ab-8262-60f14af50f23` succeeded, but its stored version 2 preview still contains duplicate content (16 blocks). A direct run of the current parser on its raw package produced 9 blocks with `duplicate_websearch_article_copy`; the discrepancy between that run and the stored job output remains unresolved.
- `nexus-app` WebSearch document test file: 20 passed. Console topic-chip tests: 2 passed. Console typecheck passed.
- API Contract, Version State, and Frontend UX human Review Gates remain required before merge.
