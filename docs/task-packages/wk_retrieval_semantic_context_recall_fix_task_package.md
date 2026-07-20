# Task Package: Retrieval Semantic Context Recall Fix

## Goal

Make `internal.search_chunks_by_semantic` return an evidence-backed section or
task context after an initial semantic hit, and introduce a two-stage hybrid
path that resolves an explicit or high-confidence automatic outline/task scope
before pgvector ranks candidates. This fixes concept/classification queries
that land on learning objectives and procedure queries that land on a task
title or knowledge-preparation node.

## Scope

- Add a read-only runtime context assembler under `nexus_app.retrieval`.
- Enrich semantic tool results with bounded `section_context` or
  `task_context` payloads, preserving original vector hits and citations.
- Prefer query/title matching over an incorrect legacy chunk-to-outline link.
- For training-operation assets, collect ordered Task Outline operation steps.
- Resolve explicit `outline_node` values as a mandatory pgvector `chunk_ids`
  scope; automatically resolved scopes may fail open to broad retrieval.
- Apply explicit theory-outline scope before pgvector ranking in `/open/v1/search`.
- Add focused tests for theory-section and task-step expansion.

## Out Of Scope

- External `/v1` response schema changes, migrations, re-embedding existing
  rows, query plaintext persistence, and a new retrieval backend.
- Changing the Console-only chunk context endpoint.
- Automatic repair/rebuild of every historical knowledge outline.

## Constraints

- Context is built only from `normalized_asset_ref`, `knowledge_chunk`,
  `knowledge_outline_node`, and `task_outline_node`; never raw content.
- Keep all context bounded and source-citable.
- Preserve the pgvector adapter as the first-stage retrieval mechanism.
- Do not use LLM-generated SQL or introduce a gateway.

## Acceptance

- A query matching a theory outline title returns that section's ordered
  chunks, even when the top vector hit is a learning-objective chunk.
- A query matching a training task returns ordered `operation_step` chunks
  beneath that task.
- A no-match query keeps its original flat hits without failing retrieval.
- An explicit `outline_node` is passed to pgvector as a pre-ranking chunk set.
- A high-confidence automatic scope falls back to broad retrieval only when
  its scoped search returns no hit.
- Focused executor tests pass.

## Review Gate

- Semantic Retrieval Integration Gate: citations stay anchored to existing
  chunks and the retrieval backend remains adapter-based.
