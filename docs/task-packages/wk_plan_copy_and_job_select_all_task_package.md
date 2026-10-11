# Task Package: Plan Copy and Job Select All

## Source Context

- `SPEC.md` places Crawler and API data sync plans in separate control flows.
- Existing create APIs own validation, scheduling, and audit for new plans.

## Goal

Let operators reuse plan settings and select all job titles or regions when creating a job collection plan.

## Scope

- Crawler and API data sync plan list actions and create forms in `nexus-console`.
- A copy action preloads a new plan without copying IDs, status, or run history.
- Select all controls for the current job category and available regions.
- Focused frontend tests and type/lint verification.

## Out Of Scope

- Backend plan cloning endpoints, upstream combination limits, or scheduler changes.

## Forbidden Changes

- Do not bypass existing create validation or audit paths.
- Do not increase the 100 job-region combination limit without upstream approval.

## Acceptance

- Copy opens a prefilled creation form and submits to the create endpoint.
- Select all and clear all update the corresponding array field.
- Combinations above 100 show a clear warning and cannot be submitted.
