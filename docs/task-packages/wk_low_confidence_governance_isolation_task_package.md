# Task Package: Low-Confidence Governance Isolation

## Source Context

- User decision: classification confidence below `0.5` is obvious noise and
  must not enter the human governance-review workflow or default asset catalog.
- `ARCHITECT.md` / `SPEC.md`: governance results remain auditable and the
  allowed core lifecycle states include `disabled`.

## Goal

Keep sub-`0.5` classification results as auditable, non-searchable isolated
assets while reserving the human review queue for actionable uncertainty.

## Scope

- Governance decision, AI-run adoption, and asset-version state projection.
- Internal review queue and default asset catalog filtering.
- PostgreSQL enum migration, focused tests, and root contract documentation.

## Out Of Scope

- Deleting raw objects, assets, normalized references, or audit evidence.
- Reclassifying historical assets or changing model prompts/rules.
- Changing public retrieval permissions or adding a new review UI.

## Acceptance

- Classification confidence `< 0.5` produces governance and asset status
  `disabled`, AI-run adoption `rejected`, and index admission `false`.
- Such results are absent from `/internal/v1/governance-reviews/pending` and
  the default `/internal/v1/assets` result, but remain auditable through an
  explicit `status=disabled` catalog query.
- Classification confidence in `[0.5, auto-adopt threshold)` remains
  `review_required`.
