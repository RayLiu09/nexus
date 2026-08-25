# Task Package: Major Profile Institution Identity Admission

## Source Context

- User report: asset `b2a5d471-8325-4fa6-a8f5-1885a1176c39` is an institution
  major-introduction page but does not expose its school in the asset record.
- `ARCHITECT.md` / `SPEC.md`: `available` requires sufficient governance and
  quality admission; raw and normalized evidence remain auditable.

## Goal

Prevent candidate institution major-introduction documents with unresolved
institution identity from entering the available asset catalog or index.

## Scope

- Normalization metadata for failed institution-profile extraction.
- Domain-quality propagation to governance admission.
- Focused tests and an auditable repair of the reported existing asset.
- Reprocess API support for retained raw objects so the reported asset can
  receive a new normalized reference under the corrected admission logic.
- Institution-profile core-model admission and knowledge-pipeline gating.

## Out Of Scope

- Inferring a school name from a URL, hostname, or model guess.
- Deleting source data or rewriting historical governance evidence.
- Changing national-standard major-profile admission.
- Requiring an institution profile to publish a national professional code.

## Acceptance

- A candidate institution profile whose strict extraction is not adopted has
  `major_profile.institution_identity_unresolved` as a blocking quality reason.
- It cannot reach `available`, chunking, indexing, or default catalog display.
- The reported historical asset is isolated with a new audit event and its
  prior governance result remains preserved.
- `POST /internal/v1/jobs/reprocess` is idempotent per request key, creates a
  new job from the retained raw object and persisted pipeline routing, and
  leaves its source version immutable.
- An institution professional introduction may have `major_code = null`, but
  it enters `major_profile_knowledge` only when it has evidence-bound school
  identity, major name, and at least two core professional fact sections
  (occupation/employment, training goal, ability, courses/training,
  certificates, or industry partnership). A document without that model is
  retained as an available full-text asset but produces no chunks or index
  manifest.
