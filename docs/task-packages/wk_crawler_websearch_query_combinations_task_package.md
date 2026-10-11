# Task Package: Crawler WebSearch Query Combinations

## Source Context

- WebSearch Custom provider accepts a single query string per request.
- Crawler runs persist one summary and ingest accepted results through the existing document pipeline.

## Goal

Allow users to enter several search terms naturally and collect the combined results in one Crawler run.

## Scope

- Accept spaces and common Chinese/English list separators in WebSearch plan queries.
- Generate bounded, ordered term combinations, query each, and deduplicate results by source URL.
- Preserve per-query failure information in the run summary and update Console guidance.
- Cover query generation, result merging, and partial provider failures with tests.

## Out Of Scope

- Provider API changes, crawler data model migrations, or Firecrawl behavior.

## Forbidden Changes

- Do not feed raw WebSearch responses directly into governance.
- Do not remove existing URL and raw-object deduplication.

## Acceptance

- A single term still makes one provider request.
- Up to four terms generate at most fifteen requests, with repeated terms removed.
- The same URL from several requests is submitted once per run.
- One failed query does not discard successful query results.
