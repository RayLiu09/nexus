# Task Package: Teaching Standard Course Library Slice 3

## Status

Implementation complete; human Review Gates remain pending before merge. This
package implements one-batch AI derivation and deterministic validation for an
existing review-state teaching-standard course projection.

## Objective

Derive one training-goal summary and the semantic fields for every course in a
standard with at most one LiteLLM call, then atomically adopt only a complete,
evidence-valid response whose immutable `course_id` set exactly matches the
input master-data rows.

## Owned Files

- `nexus-app/nexus_app/models.py`
- `nexus-app/nexus_app/enums.py`
- `nexus-app/alembic/versions/20260904_0098_teaching_standard_derivation_slice3.py`
- `nexus-app/nexus_app/teaching_standard_library/`
- `nexus-app/nexus_app/worker/runner.py`
- focused Slice-3 tests
- teaching-standard course-library contracts and architecture summaries

## Frozen Interface

- Prompt profile scenario and task type:
  `teaching_standard_course_derivation`.
- The active `ai_prompt_profile` supplies the prompt, output-schema version,
  temperature, token cap, and redaction policy. Its default model alias is
  empty; a non-empty Profile alias takes priority, otherwise the effective
  model is `DEFAULT_GOVERNANCE_MODEL`.
- One request contains the parent training-goal evidence, independent hour
  rules, and all persisted courses with their source evidence.
- One response contains `training_goal_summary` and one result for every input
  `course_id`; association by array position, name, type, or source sequence is
  forbidden.
- Unknown, missing, duplicated, or modified output IDs reject the entire batch.
- LLM returns tags, evidence references, and a controlled complexity class.
  Deterministic code renders hours, ordered-unique tags, `match_keywords`, and
  `match_text`.

## Persistence And State

- Add `teaching_standard_derivation_run` with only `prompt_profile_id` as the
  Prompt/model configuration reference; do not duplicate model/profile/prompt
  versions.
- Successful adoption updates all course-derived fields and the parent
  `training_goal_summary` in one short transaction.
- A failed call or validation writes a stable failed run and audit event but
  leaves source facts, existing complete derived values, and parent `review`
  state unchanged.
- A completed run for the same deterministic input hash is reused without
  another LLM call.

## Explicitly Excluded

- Standard activation/supersession, historical backfill, query/read APIs,
  retrieval/indexing, and Nexus Console views.
- Changes to source-owned course fields, course IDs, the 18-field business
  contract, `major_profile`, `talent_training_plan`, or capability graphs.
- Per-course LLM calls or hard-coded course-derivation model aliases.

## Acceptance

- Exactly one LiteLLM call derives all courses in one standard.
- Output order changes are harmless because adoption uses exact `course_id`.
- Any course-ID set mismatch, invalid evidence, schema failure, or invalid hour
  result causes all-or-nothing rejection.
- Practice hours never exceed total hours; overlapping standard ratios are not
  added together.
- A non-empty Profile model alias, or fallback `DEFAULT_GOVERNANCE_MODEL`, and
  the Profile's remaining call settings are used.
- Completed-input replay makes zero additional LLM calls.
- Parent status remains `review`; completion/failure is auditable without
  source text or full model output.

## Review Gates

- Data Model Gate: forward FKs, no duplicated Prompt/model fields, bounded run
  state, and no new course business field.
- AI Governance Gate: active Profile ownership, redaction policy, strict output
  Schema/evidence validation, immutable ID mapping, and no partial adoption.
- Rule Engine Gate: deterministic hour bands, practice bounds, ordered unique
  tag/match rendering, and no summing of overlapping ratios.
- Version State Gate: derivation cannot activate a standard.
- Audit Gate: completed/failed events contain hashes, counts, Profile ID, and
  stable failure code only.

## Verification

```bash
cd nexus-app
uv run pytest tests/teaching_standard_library tests/test_teaching_standard_graph.py -q
```

Evidence recorded on 2026-09-04:

- Slice-3 focused tests: 14 passed.
- Teaching-standard library and graph suite: 33 passed.
- AI-governance suite excluding the unrelated pre-existing
  `test_tag_projection.py` whitelist failures: 389 passed.
- Alembic reports the single head `20260904_0098`; Python compile checks and
  `git diff --check` pass.
- The full AI-governance run has 23 baseline failures in
  `test_tag_projection.py` because the existing code-only projection whitelist
  does not contain its legacy Pipeline-B table entries. Slice 3 does not modify
  that whitelist or projection engine.

Human review remains required for the Data Model, AI Governance, Rule Engine,
Version State, and Permission And Audit Gates defined above.
