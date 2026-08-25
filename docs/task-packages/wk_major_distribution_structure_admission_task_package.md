# Task Package: Major Distribution Structure Admission

## Source Context

- User rule: a professional major-distribution asset is a table and every
  admitted detail record must include `year`, `province_name`, `major_name`,
  `major_code`, and a non-negative `distribution_count`.
- `ARCHITECT.md`: Pipeline B record assets and Pipeline A documents are
  independent paths; AI output must pass rule guardrails before it affects an
  official governance result.
- `docs/pipeline_b_major_distribution_structured_data_design.md`: only
  `major_distribution.v1` structured records may represent this domain.

## Goal

Prevent document-style institution introductions from being adopted as
`major_distribution` merely because an AI classifier identifies a province,
major names, and incidental numeric text.

## Scope

- `nexus_app.governance.decision_service` structure guardrail for the
  `major_distribution` classification.
- Focused governance decision tests.

## Out Of Scope

- Reclassifying historical assets or deleting source data.
- Changing the `year` or `major_code` required-field contract.
- New APIs, migrations, prompt model changes, or frontend behavior.

## Acceptance

- A normalized document suggested as `major_distribution` is retained for
  audit but has no official classification, is `review_required`, and cannot
  be indexed.
- A normalized record with `major_distribution.v1`, a linked dataset, and at
  least one complete non-negative detail record can retain the classification.
- The decision trail records a stable structure-admission failure reason.
