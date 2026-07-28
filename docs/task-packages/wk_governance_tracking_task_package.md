# Task Package: Governance Tracking Consolidation

## Source Context

- `AGENTS.md`: official governance state is represented by `governance_result`
  against `normalized_asset_ref`; human overrides remain immutable and auditable.
- `WORKFLOWS.md`: this is a bounded internal API and console UX change requiring
  API Contract and Frontend UX review evidence.
- Existing `governance_review_decision`: the governance-review queue owns all
  actionable human review; the tracking page is read-only.

## Goal

Replace the duplicated, partially non-functional Governance Center tabs with a
single Governance Tracking page that shows official governance-result history
and opens the exact historical decision evidence.

## Scope

- Add a JWT-protected internal read API for paginated governance-result traces,
  enriched with asset identity and immutable review-decision metadata.
- Rebuild `/governance` as a read-only history table and result-id based detail
  Drawer.
- Rename navigation/page language from `治理中心` to `治理追踪`.
- Keep `/tag-review` as the sole pending-review and decision-submission flow.
- Add focused API and console tests.

## Out Of Scope

- Changes to AI governance execution, rule evaluation, quality scoring,
  governance-review submission, knowledge continuation, or data schema.
- Bulk adjudication, reassignment, quality-calibration writes, and new audit
  events.

## Forbidden Changes

- Do not mutate `AIGovernanceRun`, `GovernanceResult`, or
  `GovernanceReviewDecision` from the tracking page.
- Do not use an AI run as the authoritative history row.
- Do not introduce a current-result reverse pointer.
- Do not expose this internal control-plane API as a public business API.

## Deliverables

- `/internal/v1/governance-traces` read API.
- Governance Tracking table and precise historical evidence Drawer.
- Navigation and page copy updates.
- API and UI-focused tests.

## Acceptance

- Each table row represents one persisted `GovernanceResult`, including
  auto-adopted and human-reviewed results.
- A row linked to a human review displays its reviewer and review-decision
  metadata without modifying the record.
- Opening an old row fetches that exact `governance_result_id`, not the latest
  result for its normalized ref.
- `/tag-review` remains the only action path for `review_required` results.
