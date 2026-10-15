# Task Package: Asset Center Document Topic Filters

## Source Context

- `WORKFLOWS.md`: bounded task and API Contract / Frontend UX Review Gates.
- `SPEC.md` and Prototype v2.2: Asset Center document lists retain their existing type routes and pagination.
- `AGENTS.md`: use current normalized references and official governance classification; do not alter governance results.

## Goal

Show count-bearing 财经商贸类 and 低空经济类 filters above the three policy/report lists.

## Scope

- Extend the three internal document list APIs with an optional topic filter.
- Match current asset title and typed industry/topic tags on the current catalog reference.
- Fetch full-list topic totals for each list and render clickable filters with URL state.
- Add focused API and Console tests and update the repository map of behavior.

## Out Of Scope

- Persisted topic taxonomy, governance reruns, crawler relevance changes, or a forced binary classification.

## Forbidden Changes

- Do not change the existing official document classifications or version selection.
- Do not alter permission, audit, or governance mutation paths.

## Acceptance

- Filter totals include all matching visible assets, independent of pagination.
- Clicking a filter resets to page one; pagination retains the selected topic.
- Both-topic assets can appear in both filters; unmatched assets remain in the unfiltered list.
- Unknown topic values return a request validation error.
