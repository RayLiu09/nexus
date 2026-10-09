# Task Package: Job Collection C5 Runtime And Activation

## Goal

Complete the crawler-engine run lifecycle and activate the first real Provider after raw result intake is durable.

## Scope

- Poll intermediate upstream states without premature completion.
- Synchronous control acknowledgement with externally confirmed stable run state.
- Drain records after terminal upstream states before settling the existing run.
- Private deployment Catalog, migration, runtime startup, and one real query smoke run.

## Out Of Scope

- Job normalization and dictionary processing.
- A generic operations center or raw-content Console view.

## Forbidden Changes

- No real tenant key in version control, database, logs, response, or audit.
- No success state while fetched records are not persisted.
- No external HTTP call in a database transaction.

## Review Gates

- API Contract and Version State review for control semantics; Data Model and Permission/Audit review for live intake.

## Acceptance

- `pausing` and `cancelling` do not become stable local states prematurely.
- Running empty/null page does not finish the run.
- Real ten-source-page query produces matching `raw_jobs` and `raw_job_provenance` rows.
