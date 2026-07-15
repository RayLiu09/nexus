# Task Package: Teaching Standard LLM Fallback

## Goal

Improve recovery of the structured teaching-standard table when deterministic
recognition is incomplete, while retaining the frozen capability-graph model.

## Scope

- `nexus_app/teaching_standard` rule diagnostics and LiteLLM fallback.
- Pipeline A normalized-document integration and worker client wiring.
- Focused teaching-standard graph tests and this documentation.

## Contract

- Rules run first. LiteLLM is called only for a deterministic failure.
- The effective model is exactly `LITELLM_EXTRACTION_MODEL_ALIAS`.
- Input contains normalized-document blocks, TOC, and table rows only; raw
  files and MinerU raw output are excluded.
- Pydantic schema, node/edge field whitelist, literal evidence checks,
  table-row locator checks, and a `0.85` confidence threshold are required
  before data may be stored in `teaching_standard`.
- The builder remains `Major -> OccupationalDomain -> {TypicalWorkTask,
  SkillKnowledgeRequirement}`. Course, JobRole, and Ability are forbidden.
- Console presents this teaching-standard graph as `岗位知识图谱`; it is not an
  Evidence Graph.

## Out Of Scope

- New graph types, new public APIs, migrations, prompt-profile management,
  or changing the capability-staging builder.

## Deliverables And Acceptance

- Persist strategy, model alias, request/input identifiers, confidence, and
  fallback/rejection reason in normalized metadata and the normalize stage.
- Model errors or rejected output remain non-fatal and produce no graph payload.
- Run:

```bash
cd nexus-app
UV_CACHE_DIR=/tmp/nexus-uv-cache uv run pytest \
  tests/test_teaching_standard_graph.py tests/test_b8_capability_graph.py
```

## Review Gates

AI Governance Gate and Acceptance Gate: confirm source evidence is normalized,
output cannot bypass validation, and job-stage metadata contains no raw content.
