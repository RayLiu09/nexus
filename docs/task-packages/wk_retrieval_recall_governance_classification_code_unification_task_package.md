# Task Package: Retrieval Recall Governance Classification Code Unification

## Source Context

- User decision: business, governance, index, and retrieval layers must use one
  classification code. `governance.classification` is the single source of
  truth; no extra `business_domain -> knowledge_type_code -> collection`
  mapping is maintained.
- `ARCHITECT.md` / `SPEC.md`: vector collections are logical collectors by data
  asset domain type and pgvector is the P0 semantic retrieval backend.
- Current drift: `course_textbook` governance classification was mapped to
  `textbook_kb`, causing intent output and vector filters to use different
  codes.

## Goal

Make v1.0 semantic retrieval use `governance.classification` consistently from
intent recognition through chunk construction, vector collection projection,
pgvector filtering, and source metadata.

## Scope

- Update course textbook governance defaults and rules mirror so
  `primary_knowledge_type = course_textbook`.
- Update knowledge type config lookup and tests so course textbook chunks use
  `knowledge_type_code = course_textbook`.
- Update Task Outline projection defaults to write `course_textbook` chunks.
- Update pgvector projection to write `asset_domain_type`,
  `knowledge_type_code`, and collection metadata from the resolved
  governance classification.
- Update unstructured retrieval filtering to use the sub-query domain directly.
- Add a PostgreSQL migration to rename existing `textbook_kb` vector/index
  projections to `course_textbook` for current data.
- Sync root architecture/spec/readme text where it still names `textbook_kb`
  as the course textbook retrieval code.

## Out Of Scope

- Adding new semantic classifications.
- Introducing multi-code routing tables or adapter-specific mapping layers.
- Reworking structured SQL executors.
- Changing Console UI.
- Rebuilding embeddings through the worker; this slice only corrects code
  ownership and stored projection metadata.

## Forbidden Changes

- Do not reintroduce RAGFlow as semantic retrieval baseline.
- Do not add a second `business_domain` taxonomy separate from governance
  classification.
- Do not introduce new master-data reverse pointers.
- Do not loosen rule validation or AI governance guardrails.
- Do not change permissions behavior.

## Deliverables

- Code and config updates for unified classification codes.
- Alembic migration for existing course textbook projection rows.
- Focused backend tests for governance emission, chunking, projection, and
  unstructured retrieval filtering.
- Root contract documentation updates.

## Acceptance

- `course_textbook` governance output produces `course_textbook` knowledge
  emissions.
- Course textbook and Task Outline chunks use `knowledge_type_code =
  course_textbook`.
- pgvector rows for course textbook use:
  `asset_domain_type = course_textbook`,
  `knowledge_type_code = course_textbook`,
  `collection_key = course_textbook.<normalized_type>.<model>.v1`.
- Unstructured retrieval for `domain = course_textbook` filters by
  `knowledge_type_code = course_textbook`.
- Existing rows using `textbook_kb` are migrated to `course_textbook`.
