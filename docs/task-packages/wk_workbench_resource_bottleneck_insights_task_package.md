# Task Package: Workbench Resource Bottleneck Insights

## Status

In progress

## Goal

Make Workbench job health reflect final logical job outcomes and provide six-month execution/queue insights for resource bottleneck analysis.

## Scope

- Count failed jobs from the current terminal state of each durable `job` row.
- Add bounded execution-duration TOP data from completed `job_stage` intervals.
- Add six monthly queue-volume and average queue-wait trend data.
- Replace the Workbench funnel and low-value status cards with two operational charts.
- Add API, frontend, and retry-final-state tests.

## Out Of Scope

- Introducing a job-attempt history table or changing worker retry state transitions.
- Persisting Workbench snapshots or a separate metrics service.
- Changing job/list endpoint semantics.
