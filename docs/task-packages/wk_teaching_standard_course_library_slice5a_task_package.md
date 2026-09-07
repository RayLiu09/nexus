# Task Package: Teaching Standard Course Library Slice 5A

## Status

Implementation and the operator-approved historical rebuild are complete.
Slice 4 lifecycle and Nexus Console review interactions are
deferred until their interaction contract is approved. Slice 5A provides
dry-run-first historical projection and derivation into review state only.

## Objective

Discover professional teaching standards from persisted generated
`normalized_document` objects, report a bounded no-write/no-LLM execution
plan, and optionally reuse the existing Slice 1-3 services to build or refresh
review-state standard/course projections with at most one LiteLLM call per
standard.

## Owned Files

- `nexus-app/nexus_app/teaching_standard_library/backfill.py`
- `nexus-app/scripts/backfill_teaching_standard_library.py`
- `nexus-app/tests/teaching_standard_library/test_slice5a_backfill.py`
- teaching-standard task packages and architecture summaries where required

## Frozen Interface

- The CLI is dry-run by default. `--apply` is required for database writes or
  LiteLLM traffic.
- Supported filters are `--ref-id`, `--limit`, `--from-date`, and `--to-date`.
  `--retry-failed` restricts the run to libraries whose latest derivation run
  failed. `--no-llm` projects source facts only during an apply run.
- Candidate input is a `normalized_asset_ref` with `normalized_type=document`,
  `status=generated`, and latest official governance classification
  `teaching_standard`; content is read only from its persisted normalized
  object URI. A document without structurally extracted course facts is
  skipped and never projected.
- One result row reports the normalized-ref ID, bounded title, action, course
  count, whether an LLM call is required, effective model source
  (`profile`, `environment`, or `missing`), library/run IDs, and stable reason.
- Reports never contain normalized source text, Prompt text, credentials, or
  full model output.

## Persistence And State

- No backfill-run table or migration is introduced. JSON output is the batch
  report for this operational slice.
- Dry-run performs no ORM mutation, commit, audit write, or LiteLLM call.
- Apply reuses the existing standard writer, course writer, and whole-standard
  derivation service; it must not duplicate extraction or derivation logic.
- New libraries start in `review`. Existing non-review libraries are skipped.
  This slice never activates or supersedes a standard.
- Existing completed derivations for the same deterministic input hash are
  reused by Slice 3 without an additional call.
- Apply failures are isolated per normalized ref and returned under stable,
  bounded reason codes.

## Explicitly Excluded

- `review -> active -> superseded`, business-expert review commands, and all
  Nexus Console interactions.
- Query/read APIs, retrieval, chunking, indexing, reranking, and search.
- Raw-file, raw JSON, MinerU-result, or image input.
- A second implementation of teaching-standard extraction, course extraction,
  deterministic hours, or LLM response adoption.
- Automatic production-wide execution. This slice implements and tests the
  command; operators must inspect dry-run output before an approved apply run.

## Acceptance

- Default invocation is a no-write/no-LLM dry-run.
- Non-standard documents are reported and never projected.
- Apply creates or refreshes only review-state teaching-standard facts.
- Latest official governance classification bounds candidate discovery;
  keyword-only matches and standards without extracted courses are skipped.
- `--no-llm` never invokes the client or populates new derived fields; the
  existing source writer may still clear stale derived fields when source
  course facts have changed.
- A successful apply uses the Profile/environment model priority from Slice 3.
- Unchanged completed input is reused with zero additional LiteLLM calls.
- One ref failure does not roll back successful refs or abort the remaining
  batch.
- JSON totals and failure summaries agree with the per-ref outcomes.
- No course-owned field, lifecycle state, API, Console view, or index contract
  changes.

## Review Gates

- AI Governance Gate: no dry-run traffic, Slice 3 Profile/model/redaction path
  is reused, and reports contain no source content.
- Permission And Audit Gate: apply mutations use existing bounded standard and
  derivation audit events with trace IDs.
- Version State Gate: every new projection remains `review`; non-review rows
  are skipped.

## Verification

```bash
cd nexus-app
uv run pytest tests/teaching_standard_library/test_slice5a_backfill.py \
  tests/teaching_standard_library tests/test_teaching_standard_graph.py -q
```

Evidence recorded on 2026-09-04 and the approved rebuild completed on
2026-09-07:

- Slice 5A focused tests: 11 passed.
- Teaching-standard Slice 1-5A and graph suite: 45 passed.
- AI-governance suite excluding the unrelated pre-existing
  `test_tag_projection.py` whitelist failures: 389 passed.
- Black passes for every changed Python file; Python compile checks and
  `git diff --check` pass.
- Alembic remains at the single head `20260904_0098`; Slice 5A adds no table or
  migration.
- CLI help/argument loading succeeds.
- The approved historical apply produced 20 `review` standard libraries and
  537 courses. Every standard's latest derivation is `completed`; all courses
  have required tags, deterministic hours, match fields, and unique per-parent
  `course_id` values.
- The post-apply dry-run reports 20 reusable candidates, zero required LiteLLM
  calls, zero failures, and one skipped course-standard false classification.

Business-expert review and lifecycle activation remain deferred to Slice 4.
