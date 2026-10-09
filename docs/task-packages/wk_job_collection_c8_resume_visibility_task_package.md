# Task Package: Job Collection C8 Resume Visibility

## Goal

Make the separate plan and run resume controls clear while verifying a live crawler collection.

## Scope

- After a successful plan resume, open its run history so paused runs and their resume control are visible.
- Label the plan action as resuming future scheduling and show a concise success message.
- Cover the interaction with a focused Console test.

## Boundaries

- Keep the existing contract: plan resume changes future scheduling only; run resume calls the provider separately.
- Do not mutate the running job through the plan API or add a new control mechanism.

## Acceptance

- A resumed plan opens run history, which shows its paused run and run-level resume action.
- The live verification run can be resumed through the existing synchronous control service.
