# Talent Demand Report Semantic Asset Slice

## Goal

Treat `talent_demand_report` as a document-only semantic retrieval asset and provide its business list in Asset Center.

## Source context

- `ARCHITECT.md`: governance consumes `normalized_asset_ref`; Knowledge Pipeline owns chunks and indexing.
- `SPEC.md` and Prototype v2.2: professional data includes talent demand reports.
- Samples: the two talent demand PDFs in `docs/samples/`.

## Scope

- Remove report graph admission while retaining semantic chunking and indexing.
- Prevent this official classification from producing structured domain projections.
- Extract source-evidenced report identity as document metadata, with nullable fields.
- Add an internal paginated list and Asset Center table with preview, chunks, and download.
- Let business experts only fill or correct report identity fields in the Asset Center list, retaining extracted evidence and auditing every effective edit. Platform data administrators have no edit access.
- Add focused backend and frontend tests and update contract summaries.

## Out of scope

- A talent demand domain table, graph, new retrieval backend, or report statistics.
- Rewriting source PDFs or deleting historical audit data.

## Forbidden changes

- Do not ingest raw PDF or MinerU output directly into governance.
- Do not infer an institution from surveyed schools or a major code from the title alone.
- Do not alter the domain models of other classifications.

## Acceptance

- Both sample PDFs produce one report asset with semantic chunks and index eligibility.
- Neither sample generates a domain projection or evidence graph build.
- The business list shows source-backed identity, governed content tags, and all three actions.
- Expert edits affect only the current report ref's list identity; stale refs and other classifications cannot be edited.
- The edit API rejects platform data administrators and records one audit event per effective change.

## Identity Edit Contract

- `PATCH /internal/v1/talent-demand-reports/{asset_id}/identity` accepts `normalized_ref_id` and one or more non-empty `major_name`, `major_code`, `institution_name` values. `major_code` is 4-6 digits. Unrecognized fields return 422.
- Only `business_expert` may edit. Other roles receive 403; a stale ref or an asset outside the official report classification receives 409. Repeating an effective value is a no-op with no duplicate audit event.
- Manual values live in `normalized_asset_ref.metadata_summary.talent_demand_report_manual_identity`. Source-extracted `document_metadata.talent_demand_report` remains unchanged. Every effective change emits `TalentDemandReportIdentityUpdated` with actor, ref, and before/after values.
- The edit control appears only in the Asset Center report list for business experts and opens a right-side drawer. The server remains the authority for role checks.
- Existing professional domain model paths remain available for their official classifications.

## Verification And Review Gates

- Rule Engine and AI Governance: active rule v10 matches the repository rule file; `talent_demand_report` retains `semantic_repack` without `graph_profile`. Official classification gates domain projection and graph admission. Rule changes and historical cleanup were audited.
- Data and semantic retrieval: the targeted maintenance pass retired 8 erroneous major-profile projections and 8 graph builds, cleaned 27 report refs, and left 97 existing semantic chunks intact. A repeat dry run found no remaining targeted projections.
- API and frontend: the paginated internal report list reads document metadata and governed tags; the table exposes preview, RAG chunks, and original download through existing permission-controlled routes. API tests (18) and frontend tests (6) passed; TypeScript typecheck passed.
- Adjacent classification regression: 43 tests passed across report identity, document parsing, teaching-standard projection, and document worker routing. The broader targeted app suite previously passed 52 tests.
- Sample evidence: PDF text-layer inspection yielded `大数据与会计` with unknown code/institution and `大数据技术（含地理信息应用方向）` with code `510205` and unknown institution. Neither PDF has completed a fresh MinerU ingest and index run in this environment.
- Human Review Gates required before merge: Data Model, AI Governance, Rule Engine, Semantic Retrieval Integration, API Contract, and Frontend UX. This record provides review evidence; human approval and full PDF end-to-end acceptance remain pending.
