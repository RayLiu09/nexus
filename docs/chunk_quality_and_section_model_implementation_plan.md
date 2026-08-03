# Chunk Quality And Section Context Optimization Implementation Plan

Status: draft implementation plan  
Date: 2026-08-01  
Scope: retrieval quality improvement for policy/report assets and textbook/book assets  
Write boundary: no database writes for the first quality-analysis pass

## 1. Objective

NEXUS does not need to copy external "by title" or "by similarity" chunking
strategies as product features. They are useful comparison baselines only.
The implementation objective is to improve retrieval and recall quality for:

- policy documents
- industry reports and white papers
- course textbooks
- theory books
- practical training textbooks

The target quality is:

- search hits are semantically relevant;
- answer contexts are complete enough for QA;
- citations remain traceable to `normalized_asset_ref`, `knowledge_chunk`,
  source block ids, and locators;
- noisy chunks do not dominate retrieval;
- policy/report assets gain section-level context comparable to existing
  textbook outline context;
- chunk quality becomes measurable before index admission or rebuild.

## 2. Current Baseline

Current semantic document chunks are generated through:

```text
normalized_document.blocks
  -> semantic_repack
  -> knowledge_chunk
  -> pgvector projection
  -> semantic search
  -> optional outline/task context expansion
```

The current implementation already provides:

- navigational and low-information block filtering;
- document metadata block exclusion from chunk candidates;
- page footer, TOC, QR code, publication/copyright noise filtering;
- figure/table attribution folding;
- cross-page paragraph continuation repair;
- row-record table decomposition into overview and row chunks;
- `heading_path`, `source_block_ids`, `locator`, `md_char_range`, and
  `md_spans` provenance;
- textbook `KnowledgeOutlineNode` and task-outline context expansion;
- pgvector similarity search with optional ref/chunk filters.

This is already stronger than recursive chunking. The largest product gap is
not "missing by title chunking"; it is the absence of a general document
section model for non-textbook policy/report documents, plus the absence of a
formal chunk quality report.

## 3. Constraints

- Governance input remains `normalized_document` or `normalized_record` via
  `normalized_asset_ref`. Raw files, raw JSON, and MinerU raw output are not
  valid governance or knowledge inputs.
- Knowledge Pipeline remains independent of Asset Pipeline.
- `knowledge_chunk.normalized_ref_id` continues to link chunks to
  `normalized_asset_ref`.
- No reverse pointers are added to `asset`, `asset_version`, or
  `normalized_asset_ref`.
- The first quality-analysis pass must not write database rows.
- Policy/report section modeling must use normalized blocks and existing
  chunk provenance, not raw source content.
- `/open/v1/search` remains compact chunk evidence unless API contract review
  explicitly changes it.
- `/open/v1/query` and internal query APIs may return richer contexts.

## 4. Proposed Workstreams

### 4.1 Chunk Quality Report

Add a read-only quality-analysis tool and document output. The first slice
generates a Markdown report under `docs/` and does not persist database state.

Recommended analysis dimensions:

| Dimension | Metrics |
| --- | --- |
| Structure coverage | `chunk_count`, `chunks_without_locator_count`, `chunks_without_source_block_ids_count`, `chunks_without_heading_path_count`, `heading_path_coverage_ratio` |
| Size distribution | `avg_char_count`, `p50_char_count`, `p95_char_count`, `max_char_count`, `over_hard_max_count`, `near_empty_count` |
| Boundary risk | `cross_page_chunk_count`, `cross_heading_suspected_count`, `merged_block_chunk_count`, `single_large_block_chunk_count` |
| Noise risk | `toc_like_chunk_count`, `copyright_like_chunk_count`, `page_footer_like_chunk_count`, `prompt_like_chunk_count`, `low_information_chunk_count` |
| Table quality | `table_overview_count`, `table_row_count`, `large_table_not_decomposed_count`, `table_locator_precision_distribution` |
| Outline/section quality | `outline_linked_chunk_count`, `outline_link_coverage_ratio`, `outline_link_stale_suspected_count`, `section_expansion_available` |
| Retrieval readiness | `index_admission_hint`, `warnings`, `recommended_actions` |

Initial thresholds:

| Check | Warning threshold | Block threshold |
| --- | ---: | ---: |
| missing locator ratio | > 5% | > 20% |
| missing heading path ratio for documents | > 20% | > 50% |
| over hard max chunks | > 0 | > 5% |
| near-empty chunks | > 2% | > 10% |
| low-information chunks | > 5% | > 15% |
| large table not decomposed | > 0 | manual review |
| outline stale suspicion | > 0 | rebuild recommended |

The first implementation should be a script or service helper that accepts:

```text
normalized_ref_id optional
knowledge_type_code optional
asset domain optional
status filter default available/completed refs
output path default docs/chunk_quality_report.md
```

It must use read-only sessions and must not update chunks, refs, manifests, or
jobs.

### 4.2 Policy/Report Document Section Model

Introduce a general section model for policy and report assets. This is not a
replacement for chunks. It is a context layer that groups existing chunks into
business-readable document sections.

Candidate logical model:

```text
document_section
  id
  normalized_ref_id
  parent_id
  level
  title
  order_index
  heading_path
  source_block_ids
  locator
  section_type
  chunk_count
  char_count
  quality_flags
```

Candidate chunk relation:

```text
knowledge_chunk.document_section_id
```

For the first implementation slice, avoid a migration if the team wants a
low-risk prototype. A derived in-memory section map can be built from
`knowledge_chunk.locator.heading_path` and chunk order. After quality is proven,
promote it to a persisted model through Data Model Gate review.

Section extraction rules for policy/report P0:

1. Use `normalized_document.blocks[]` headings and `knowledge_chunk.locator`.
2. Build h1/h2/h3 tree as chapter/section/subsection.
3. Attach chunks by chunk order and deepest matching `heading_path`.
4. Keep table rows under the nearest section.
5. Detect suspicious missing headings and mark the section model partial.
6. Do not infer section content from raw files or ungrounded LLM output.

Retrieval behavior:

- First-stage retrieval remains pgvector chunk search.
- When policy/report hits belong to a section, rank candidate sections using:
  vector score, title relevance, supporting hit count, first-hit rank, and weak
  evidence penalties.
- `/open/v1/query` and `/internal/v1/query` may return `section_contexts` for
  policy/report assets after API Contract Gate review.
- `/open/v1/search` stays compact hit evidence.

### 4.3 Hard-Max Guard For Oversized Chunks

Add a post-process guard after semantic units are created and before
`KnowledgeChunk` construction:

```text
if semantic_unit.content length > hard_max:
  split by paragraph, sentence, list item, or table row
  preserve heading_path
  preserve source_block_ids and md_spans where possible
  set chunk_metadata.split_reason = hard_max_guard
```

This is not a general "by character" strategy. It is a safety guard to prevent
abnormally large chunks from weakening embeddings.

### 4.4 Weak Evidence Role

Add a retrieval role classification in chunk metadata or retrieval-time
annotations:

```text
answer_candidate
context_only
weak_evidence
navigation
```

Examples:

- learning objectives: `context_only` or `weak_evidence`
- TOC-like content: `navigation`
- task steps: `answer_candidate`
- table rows: `answer_candidate`
- figure attribution alone: `context_only`

The first slice can remain runtime-only and avoid database writes.

### 4.5 Retrieval Evaluation Set

Create a small evaluation set per domain:

- policy/report: policy issuer, effective scope, requirements, comparisons,
  chapter summaries, table facts;
- industry reports: market size, trend, drivers, risks, cases, chart data;
- theory textbooks: definition, classification, method, comparison;
- practical training textbooks: process, step sequence, tool parameter,
  precautions.

Metrics:

```text
top5_recall
answer_context_recall
citation_precision
section_context_hit_rate
weak_hit_ratio
no_answer_false_positive_rate
```

This should become the main decision tool for chunk/retrieval optimization.

## 5. Delivery Sequence

### Slice 1: Read-Only Chunk Quality Report

Deliverables:

- read-only quality-analysis helper or SQL script;
- generated `docs/chunk_quality_report.md`;
- no database writes;
- no migrations;
- no API behavior changes.

Acceptance:

- completed/available normalized refs are listed;
- each analyzed ref has chunk count, locator coverage, heading coverage, size
  distribution, table/outline signals, warnings, and recommendations;
- the report explicitly states any environment or data-access limitation.

### Slice 2: Derived Policy/Report Section Prototype

Deliverables:

- runtime section grouping helper for policy/report chunks;
- unit tests with synthetic policy/report chunks;
- no persisted model yet unless approved.

Acceptance:

- section groups are deterministic from chunk order and heading path;
- table row chunks attach to nearest section;
- section candidates can be ranked from existing hits.

### Slice 3: Query-Time Section Context For Policy/Report

Deliverables:

- section context assembler for policy/report query APIs;
- API contract update if response shape changes;
- tests for policy/report section expansion.

Acceptance:

- `/open/v1/search` remains compact;
- query APIs can return bounded policy/report `section_contexts`;
- citations preserve chunk id, normalized ref id, locator, and source block ids.

### Slice 4: Quality-Guided Rebuild And Hard-Max Guard

Deliverables:

- oversized semantic unit split guard;
- quality report warnings linked to rebuild recommendations;
- regression tests for overlong paragraphs and large tables.

Acceptance:

- oversized chunks are split deterministically;
- provenance is not lost;
- no raw-content dependency is introduced.

## 6. Review Gates

| Gate | Trigger |
| --- | --- |
| Semantic Retrieval Integration Gate | chunk quality report, section grouping, retrieval context expansion |
| API Contract Gate | adding policy/report section contexts to public/internal query responses |
| Data Model Gate | persisting `document_section` or adding `knowledge_chunk.document_section_id` |
| Permission And Audit Gate | exposing new contexts through open/internal APIs |
| Acceptance Gate | retrieval evaluation set and quality metrics used for milestone acceptance |

## 7. Open Decisions

1. Should `document_section` be persisted in P0.2, or should NEXUS first run a
   derived runtime prototype?
2. Should policy/report `section_contexts` reuse the textbook response shape
   exactly, or use a domain-specific `document_section_context` kind?
3. What hard-max should be used for Chinese report chunks: 1024 chars,
   1500 chars, or token-count based?
4. Should weak evidence role be persisted in `chunk_metadata`, or computed only
   during retrieval until the quality report proves stability?
5. Which asset statuses count as "completed" for the first report:
   `available` only, or `available` plus governed `review_required` refs?

