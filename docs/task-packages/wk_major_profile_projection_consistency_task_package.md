# Task Package: Major Profile Projection Consistency

## Source Context

- `AGENTS.md`: governance results target `normalized_asset_ref`; knowledge
  processing remains independent and uses the official governed result.
- `docs/pipeline_a_major_profile_structured_data_design.md`: `major_profile`
  applies only to professional introduction documents and supplies a
  structured profile view plus `major_profile_knowledge` chunks.
- `WORKFLOWS.md`: this touches normalized metadata, governance and semantic
  retrieval presentation; focused tests and review evidence are required.

## Goal

Prevent non-major documents from acquiring a publishable `major_profile.v1`
projection, reconcile a stale projection when final governance disagrees, and
ensure Console knowledge views follow the official classification and current
knowledge emission.

## Scope

- Tighten deterministic Pipeline A major-profile extraction admission.
- Suppress incompatible major-profile presentation metadata after AI or human
  governance decisions, with audit evidence.
- Add a Console routing guard for historical inconsistent metadata.
- Add focused backend and frontend regression tests.

## Out Of Scope

- Reclassifying historical assets, bulk data repair, new taxonomy codes,
  manual profile editing, or a new API endpoint.

## Forbidden Changes

- Do not overwrite governance results or immutable review decisions.
- Do not change `knowledge_emissions` except through the existing official
  classification lookup.
- Do not delete historical domain rows in this code slice.
- Keep `program_profile` as a compatibility classification for existing
  legitimate professional-introduction assets.

## Acceptance

- A report containing publication/CIP numbers and scattered professional terms
  cannot emit a `major_profile.v1` projection.
- A final `industry_report` result cannot select the major-profile Console
  view, even if historical metadata retains that marker.
- Legitimate `major_profile` and `program_profile` assets retain their
  structured views and `major_profile_knowledge` emission.
