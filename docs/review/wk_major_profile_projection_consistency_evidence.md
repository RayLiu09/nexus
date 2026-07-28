# Major Profile Projection Consistency Evidence

Date: 2026-07-28

## Scope

- Task package: `wk_major_profile_projection_consistency_task_package.md`.
- Corrects false `major_profile.v1` presentation projections for Pipeline A
  documents and prevents stale metadata from selecting the wrong Console view.
- No schema, migration, public API, governance-result, or immutable
  governance-review-decision change.

## Contract Review

| Gate | Evidence |
| --- | --- |
| AI Governance | The source AI result remains unchanged. The active-rule classification remains the only source of knowledge emissions. |
| Semantic Retrieval | Specialized major-profile presentation requires a matching official classification and `major_profile_knowledge` emission. Other documents retain their normal RAG chunk presentation. |
| Version State | No version transition logic changes. Projection suppression is derived metadata only and is audited in the transaction that creates the official result. |
| Audit | Suppression writes `DomainNormalizeCompleted` with action `presentation_projection_suppressed`, prior profile type, official classification, and removed metadata keys. |

## Regression Coverage

- A report containing publication/CIP-like number `9085` plus professional
  terminology cannot produce a publishable major-profile projection.
- `industry_report` suppresses a stale major-profile presentation marker while
  preserving its `industry_research_kb` emission.
- `program_profile` remains a compatibility classification for legitimate
  existing professional-introduction assets.
- Console routing requires the derived profile, official classification, and
  current major-profile emission to agree.

## Verification

```text
cd nexus-app
UV_CACHE_DIR=/tmp/nexus-uv-cache uv run pytest \
  tests/test_major_profile.py \
  tests/governance/test_review_service.py \
  tests/governance/test_pipeline_integration.py -q

35 passed
```

```text
cd nexus-console
npm run typecheck
npm test -- --run lib/api.test.ts
```

Type check passed. The focused Vitest run passed with 23 tests. Full
`npm run lint` completed with 0 errors; it reports 81 pre-existing warnings
outside this change's scope.
