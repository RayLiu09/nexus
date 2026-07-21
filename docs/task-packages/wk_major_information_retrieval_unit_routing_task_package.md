# Task Package: Major Information Retrieval Unit Routing

## Source Context

- `ARCHITECT.md`: semantic retrieval remains adapter-based and every answer must preserve chunk / normalized-reference traceability.
- `WORKFLOWS.md`: semantic retrieval integration changes require focused tests and Semantic Retrieval Integration Gate review.
- `config/query_router_tools.json`: current `scenario_3` incorrectly treats professional teaching-standard headings as textbook outline nodes and requires a graph call for every query.
- Domain contract confirmed by business owner:
  - Professional introductions project to `MajorProfile` and related tables and use `major_profile_knowledge` chunks.
  - Professional teaching standards use `course_standard_authoring_process` chunks and are the source of capability graphs.
  - Shared professional facts are read from domain tables first and filled per missing requested unit from chunks; graphs are requested explicitly only.

## Goal

Return professional basic information accurately without exposing asset-source choices to users: use the professional-introduction read model for exact facts, fall back per requested data unit to professional-introduction or teaching-standard chunks, and query teaching-standard graphs only when the user requests a graph representation.

## Scope

- `config/query_router_tools.json`
- `nexus-app/nexus_app/retrieval/dispatcher_v2.py`
- `nexus-app/nexus_app/retrieval/prompt_profiles_v2.py`
- `nexus-app/nexus_app/retrieval/subject_routing.py`
- `nexus-app/nexus_app/retrieval/tool_executors_v2.py`
- `nexus-app/nexus_app/retrieval/composer_v2.py` and its prompt policy where needed
- Focused retrieval tests under `nexus-app/tests/retrieval/`

## Out Of Scope

- Asset reprocessing, historical chunk repair, or new database tables/migrations.
- Changing `/open/v1/search` or `/open/v1/qa` response schemas.
- Changing teaching-standard extraction or graph construction.
- New retrieval infrastructure, BM25, tsvector, OpenSearch, Elasticsearch, RAGFlow, or a new service.

## Forbidden Changes

- Do not use `KnowledgeOutlineNode`, `TaskOutlineNode`, `outline_node`, or `outline_code` as the professional teaching-standard retrieval contract.
- Do not make a capability graph call mandatory for a professional-information query.
- Do not synthesize or silently merge conflicting values from distinct source assets.
- Do not output unrequested fields or `暂无数据` for unrequested units.

## Deliverables

- A unit-aware `internal.query_major_information` tool.
- Scenario 3 schema and dispatcher behavior that choose graph retrieval only for explicit graph requests.
- Versioned `retrieval.intent_v2` prompt update and a data-backed route guard for known-major basic-information requests.
- Field-level structured-first and chunk-fallback evidence with `chunk_id`, `normalized_ref_id`, and locator.
- Regression tests for basic information plus occupation orientation, missing-unit fallback, and graph opt-in.
- Deterministic graph-result rendering: successful graph queries bypass LLM; absent graph assets return a direct no-asset result.

## Acceptance

- `网络营销与直播电商专业基本信息和职业面向` invokes no graph tool and returns structured `MajorProfile` / `MajorProfileOccupation` data when present.
- A requested missing unit falls back only to `major_profile_knowledge` / `course_standard_authoring_process` chunks, never an outline-node scope.
- An explicit capability-graph query invokes the teaching-standard graph tool.
- Composer does not add unrequested statistics or unavailable-field statements.
- A successful role/capability graph query never produces a generated skill summary.
- Focused retrieval tests pass.
