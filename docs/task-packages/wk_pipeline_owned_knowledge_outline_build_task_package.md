# Pipeline-Owned Knowledge Outline Build Task Package

## Context

User analysis found that asset `7e582a43-98a6-4828-a8bd-705d0f0d4d5c`
(`2.现代零售行业的关键特征.pdf`) was available and had `course_textbook`
chunks, but had no `task_outline_profile`, no `knowledge_outline_node`, and no
`knowledge_chunk.knowledge_outline_node_id` links. The detector dry-run classified
the corresponding normalized ref as `theory_knowledge`, so the missing outline was
a pipeline orchestration gap rather than an asset eligibility issue.

## Objective

Make knowledge outline construction part of the normal knowledge pipeline for
eligible course-textbook document refs, while minimizing impact to existing
chunking, indexing, and smart retrieval behavior.

## Scope

- Add a pipeline stage after `knowledge_chunking` and before `index_submit`.
- Run only for document refs with `course_textbook` chunks or emissions.
- Detect textbook subtype from the normalized document payload.
- Reuse existing `task_outline_profile` without overwriting it; create a
  profile only when subtype detection says the ref is knowledge-outline
  eligible and no profile exists yet.
- Build `knowledge_outline_node` only for eligible subtypes:
  `theory_knowledge` and `hybrid`.
- Backfill `knowledge_chunk.knowledge_outline_node_id` through the existing
  `build_and_persist_outline` service.
- Make the stage non-blocking during rollout: failures are captured as job-stage
  failures and logs, but do not prevent `index_submit`.

## Out Of Scope

- No schema migration.
- No changes to query router, semantic retrieval, pgvector search, or composer.
- No historical full rebuild.
- No change to `knowledge_chunk` contract beyond populating the existing
  `knowledge_outline_node_id` column.
- No new async job type or queue.
- No LLM heading classification path changes.

## Files

- `nexus-app/nexus_app/pipeline/stages.py`
- `nexus-app/nexus_app/worker/runner.py`
- `nexus-app/tests/governance/test_pipeline_integration.py`
- `ARCHITECT.md`
- `SPEC.md`
- `readme.md`

## Acceptance Criteria

- New eligible `course_textbook` document refs build knowledge outline before
  index submission.
- The stage preserves any existing `task_outline_profile`; eligible refs without
  a profile get one before outline construction.
- The stage populates `knowledge_outline_node` rows and links leaf chunks via
  `knowledge_chunk.knowledge_outline_node_id`.
- Non-eligible refs produce a skipped stage.
- Stage failure is observable but non-blocking.
- Existing smart retrieval code paths are untouched.

## Verification

```bash
uv run pytest tests/governance/test_pipeline_integration.py -k KnowledgeOutlineBuildStage
uv run pytest tests/knowledge_outline/test_service.py
```
