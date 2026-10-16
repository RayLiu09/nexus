# Teaching Case Semantic Asset Slice

## Source context

- `ARCHITECT.md`, `SPEC.md`, and Prototype v2.2: governance reads normalized refs; the Teaching Resources Asset Center reserves a Teaching Cases entry.
- Seven teaching-case DOCX samples in `docs/samples/`; the livestream ecommerce lesson plan is excluded.
- `WORKFLOWS.md`: Rule Engine, AI Governance, Semantic Retrieval, API Contract, and Frontend UX gates apply.

## Goal

Classify teaching-case documents, retain semantic chunks without a domain structure model, and show a usable business list.

## Scope

- Add `teaching_case` to staged and active governance rules with one `nexus_semantic` knowledge emission and no graph profile.
- Extract a source-backed case title from normalized document content; remove a leading `教学案例——` display prefix.
- Retire the unused active `case_decompose` strategy and its unbound knowledge-type branches, preserving historical migrations and archived rules.
- Add current, paginated internal case list/count and Console preview, chunk, and original-download actions.
- Add focused rules, API, normalization, and Console tests; update contract summaries.

## Out of scope

- Case domain tables, graph/outline generation, public business API, and edits to sample documents.
- Treating the livestream ecommerce lesson plan as a case.

## Forbidden changes

- Do not govern from raw DOCX or MinerU output.
- Do not add reverse pointers or bypass governance decisions.
- Do not remove historical database enum values or migration records.

## Acceptance

- Seven cases classify as `teaching_case` and emit semantic chunks with source locators; the lesson plan does not.
- Content titles take priority over filenames, and a leading `教学案例——` is removed in the list.
- The business list and count agree on current visible refs; actions use existing authenticated preview, chunks, and download paths.
- No case domain projection, knowledge outline, or evidence graph build is generated.

## Verification evidence

- Seven source DOCX titles passed direct OOXML content-title extraction tests.
- Focused normalize, semantic-repack, knowledge-emission, and Office pipeline tests passed (129 tests).
- Affected internal API tests passed (22 tests), including current-list tags/counts and graph rejection.
- Console TypeScript and targeted Vitest checks passed; ESLint could not start because `eslint-plugin-testing-library` is missing from the existing install.
- Audited active governance rules v13 contains the new classification criteria and semantic emission; the local API loaded v13 with background workers disabled.
- Full MinerU ingestion of the seven documents and human Review Gates remain for integration acceptance.
