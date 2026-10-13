# Task Package: Local Governance Rules Sync

## Source Context

- `ARCHITECT.md` and `SPEC.md`: governance rules are versioned, validated, and auditable.
- `WORKFLOWS.md`: Rule Engine Gate and bounded task package requirements.
- `config/governance_rules_v2.json`: reviewed deployment mirror for the active rules.

## Goal

Update the local database rule version to remove the retired `job_demand` classification from the rules page, then restart the local API so its rule cache uses the new version.

## Scope

- `nexus-app/scripts/sync_governance_rules_from_file.py` validation and audit summary.
- Local `governance_rules_version` publication through the existing service and local `nexus-api` restart.
- Verification of version status, audit trail, classification list, and API health.

## Out Of Scope

- Reclassification or deletion of historical governance results and assets.
- Rule engine expressions, database schema, API contracts, and Console UI changes.

## Forbidden Changes

- Do not bypass `GovernanceRulesService` or its audit events.
- Do not alter historical governance decisions or unrelated rule definitions.
- Preserve all architecture boundaries in `AGENTS.md`.

## Deliverables And Acceptance

- A validated new active rule version; prior version archived with audit records.
- Diff limited to removal of `job_demand` and its structured-record knowledge-type applicability.
- Restarted local API returns HTTP 200 and serves the new active rule version.
- Rule Engine Gate evidence: schema validation, exact diff review, version/audit checks.
