# Task Package: Evidence Graph Policy/Report Profile Resilience

## Task name

Make Evidence Graph extraction profile-aware for short policy documents and
chapter-structured reports, and retain safe diagnostics for malformed model output.

## Source context

- `ARCHITECT.md`: Evidence Graph input is `normalized_asset_ref` plus
  `knowledge_chunk` evidence only; raw objects and MinerU output are forbidden.
- `docs/evidence_graph_contextual_unit_design.md`: chunks remain evidence
  boundaries while extraction uses contextual units.
- `config/governance_rules_v2.json`: `industry_policy` and report
  classifications share `industry_research_kb`, so classification-level graph
  profile selection is necessary.

## Goal

Route policies to policy-specific graph extraction and preserve their compact,
non-chapter-oriented context. Keep reports grouped by actual chapter structure.
Give operators safe structural diagnostics when a model response cannot be
parsed as graph candidates.

## Scope

- Classification-level `graph_profile` declarations and deterministic emission
  projection, including a dedicated `talent_demand_report` knowledge type and
  collection separate from `industry_research_kb`.
- Remove legacy `ragflow` nodes from active governance knowledge-type
  configuration; NEXUS retrieval remains adapter/pgvector based.
- Policy-specific body-unit grouping; report grouping remains heading-based.
- Redacted model-response structure diagnostics in graph build quality summary.
- Focused unit, extractor, and knowledge-emission tests.
- Contextual-unit design documentation.
- Publish the reviewed local governance rules as a new audited DB rules version.
- Migrate existing `industry_policy` graph-profile projections by retiring
  prior `report_document` graph builds and creating replacement
  `policy_document` builds. Existing build rows remain immutable evidence of
  their original strategy.

## Out of scope

- Database schema migrations and changes to the public graph API.
- Persisting model raw responses, normalized source text, API keys, or secrets.
- Replacing the LLM body extractor with deterministic extraction.

## Forbidden changes

- Do not source graph input from raw files, raw JSON, or MinerU output.
- Do not make graph construction depend on Top-K retrieval or UI pagination.
- Do not bypass governance rules when choosing a graph profile.
- Do not add reverse pointers to normalized refs, versions, or chunks.
- Do not rewrite an existing graph build's `graph_profile`; retire it and create
  a replacement build so the historical strategy remains auditable.
- Do not change a normalized document, asset/version state, official governance
  result, or knowledge chunk solely as part of this profile migration.

## Acceptance

- `industry_policy` emits `industry_research_kb` + `policy_document`; industry
  and sector reports emit `industry_research_kb` + `report_document`; talent
  demand reports emit their dedicated `talent_demand_report` knowledge type +
  `report_document`.
- Short policy chunks without headings form a single policy document unit until
  normal size limits require windows.
- Report chunks remain separated at chapter boundaries.
- Invalid model response diagnostics expose only structural metadata and call
  correlation fields, never raw content.
- Evidence Graph warnings remain diagnostics only; graph builds never enter
  `review_required`.
- Publishing rules archives the previous active version and creates the next
  active version with audit rows.
- Every affected historical `industry_policy` graph build is either already
  represented by a policy-profile build or has its old report-profile build
  retired and a replacement policy-profile build queued or completed.
- Focused tests pass.
