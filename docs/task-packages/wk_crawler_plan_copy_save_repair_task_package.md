# Task Package: Crawler Plan Copy Save Repair

## Source Context

- `SPEC.md` requires Crawler plans to be copied through a prefilled new-plan form.
- Console uses the normal Crawler plan create endpoint for copied plans.

## Goal

Identify and fix server errors when saving a copied Crawler plan.

## Scope

- Reproduce copy requests through the real API for Firecrawl and WebSearch.
- Repair the failing configuration path and add a focused regression test.
- Verify error responses remain actionable when copied values are invalid.

## Out Of Scope

- New Crawler plan fields, database migrations, or changes to ingestion.

## Forbidden Changes

- Do not duplicate a plan by copying its database row or bypassing create validation.

## Acceptance

- Copying a valid plan creates a separate plan with editable settings preserved.
- Invalid copied configuration returns a client error rather than an uncaught server error.
