# Teaching Standard Course Library v1 Contract

## Status

Slice 0 implementation contract. This document freezes the domain boundary
before persistence code is introduced.

## Purpose

`teaching_standard_library` represents one evidence-bound national or industry
professional teaching standard. `teaching_standard_course` represents the
standard-course baseline derived from that standard. Neither model represents
an institution's actual curriculum.

The only valid source is the complete persisted `normalized_document` selected
by `normalized_asset_ref`. Raw files, raw JSON, MinerU output, page images,
and crawler source payloads are not domain-extraction inputs.

## Domain Boundary

```text
normalized_asset_ref (one document version)
  -> teaching_standard_library (one projection)
     -> occupation facts
     -> hour-rule facts
     -> standard-course rows
     -> internal derivation provenance
```

The library has no reverse pointer on `asset` or `asset_version`. Existing
`teaching_standard.v1` capability graphs, `course_standard.v1` document
graphs, `major_profile.v1`, and `talent_training_plan.v1` remain independent.

## Standard Status

`teaching_standard_library.status` is not an `asset_version` status.

| Status | Meaning | Allowed predecessor |
| --- | --- | --- |
| `review` | All source and derived course rows are built; whole-standard business review is pending. | initial construction |
| `active` | A business expert has approved the standard and its complete course set. | `review` |
| `superseded` | A later effective standard replaces it for default use. | `review`, `active` |

New library rows always start as `review`. A lifecycle command, not LLM output
and not general asset governance, performs `review -> active`. Every state
change requires an audit event and actor/trace metadata. Courses do not carry
their own status, confidence, confirmation, or review columns.

## Course Business Contract

The public/business course shape contains exactly 21 fields.

| # | Field | Source/derivation rule |
| ---: | --- | --- |
| 1 | `course_id` | Deterministic: `VC<major_code>-<type><sequence>`; never LLM generated. |
| 2 | `standard_course_name` | Literal core-table `课程涉及的主要领域`; literal list item for foundation/extension. |
| 3 | `major_code` | Standard identity evidence. |
| 4 | `major_name` | Standard identity evidence. |
| 5 | `education_level` | Admission-requirement/standard identity evidence. |
| 6 | `course_type` | `foundation`, `core`, or `extension`, represented with agreed display labels. |
| 7 | `suggested_total_hours` | Deterministic rule result using batch complexity result. |
| 8 | `suggested_practice_hours` | Deterministic rule result; never exceeds total hours. |
| 9 | `suggested_hours_range` | Deterministic rule result. |
| 10 | `hours_setting_basis` | Deterministic explanation with rule version. |
| 11 | `typical_work_task_description` | Literal core-table text; empty where unavailable. |
| 12 | `teaching_content_requirement` | Literal core-table text; empty where unavailable. |
| 13 | `knowledge_tags` | Batch derivation, validated against source evidence. |
| 14 | `skill_tags` | Batch derivation, validated against source evidence. |
| 15 | `tool_tags` | Source-evidenced tool extraction; `无特定工具要求` if absent. |
| 16 | `literacy_tags` | Batch derivation constrained by source evidence. |
| 17 | `match_keywords` | Deterministic ordered unique render. |
| 18 | `match_text` | Deterministic fixed-template render. |
| 19 | `source_standard` | Literal standard title/identity. |
| 20 | `source_section` | Normalized heading path. |
| 21 | `source_page` | Page/table-row evidence locator render. |

Internal UUIDs, parent IDs, normalized-ref IDs, asset-version IDs, source
sequence, raw evidence locator, timestamps, and derivation audit/provenance
are not business fields and must not be exposed as a twenty-second field.

## Source Extraction Rules

- Professional identity, admission requirement, study duration, occupation
  orientation, training goal, curriculum structure, and hour rules are derived
  only from semantic headings plus normalized blocks.
- Core-course rows use the four-column table: sequence, `课程涉及的主要领域`,
  `典型工作任务描述`, and `主要教学内容与要求`.
- A core table row maps exactly once to a course. The second column supplies
  the course name without additional course-name inference.
- Foundation and extension course lists are split deterministically on Chinese
  enumeration punctuation, retaining literal list names. Their unavailable
  task/requirement fields are empty.
- Cross-page continuation merging requires the same source table identity,
  compatible sequence, and adjacent continuation evidence. Repeated headers
  are not source data.
- Public foundation courses, practice projects, internships, graduation work,
  and other reference-defined non-course items are excluded unless explicitly
  included in a professional-course list.
- Duplicate key: `major_code + education_level + course_type +
  standard_course_name`. Keep one row and record a bounded duplicate diagnostic.
- Public-foundation, professional-course, practice, elective, and internship
  hour rules are persisted as independent literal constraints. Practice hours
  can occur within both public-foundation and professional courses, and
  elective hours can occur within either group; these dimensions are not
  mutually exclusive and their values must never be added together for a
  total-hours validation.

## One-Call Batch Derivation Contract

One standard may issue no more than one LLM derivation request after deterministic
source extraction. The request contains the standard's evidence-bounded
training goal/specification, hour rules, and all candidate courses. The
response contains:

```text
training_goal_summary
courses[] keyed by stable source sequence
  -> knowledge_tags, skill_tags, tool evidence references,
     literacy_tags, complexity_classification
```

The request excludes raw document bytes and any data from other standards.
The response must be schema-valid, refer only to known course identifiers and
block/row evidence, and cannot change literal source fields. One malformed or
failed response records a stable derivation failure and leaves the parent
library in `review`.

The following are deterministic and must never cause an LLM call: section
recognition fallback rules, list splitting, core-row merge/de-duplication,
course IDs, tag ordered-deduplication, suggested-hour bounds/ratios,
`match_keywords`, and `match_text`.

## Derivation Run Provenance

`teaching_standard_derivation_run` records one batch execution for one
standard. It stores the immutable `ai_prompt_profile` row ID only; it does not
duplicate the profile's `profile_version`, `prompt_version`, or
`litellm_model_alias` values.

```text
teaching_standard_derivation_run
  id: UUID primary key
  library_id: UUID -> teaching_standard_library.id
  prompt_profile_id: UUID -> ai_prompt_profile.id
  derivation_version: string
  input_hash: string
  output_hash: string | null
  status: pending | completed | failed
  failure_code: string | null
  created_at: timestamp
  completed_at: timestamp | null
```

The profile reference is mandatory for any LLM-backed execution. It is NULL
only for a deterministic no-LLM derivation record, should one be persisted.
Joining `prompt_profile_id` to `ai_prompt_profile` is the only supported way
to recover model alias, Profile version, prompt version, template, output
schema, temperature, token cap, and redaction policy.

## Proposed Audit Events And Failure Codes

| Kind | Stable value | Trigger |
| --- | --- | --- |
| Audit | `TeachingStandardLibraryGenerated` | Standard/course projection written. |
| Audit | `TeachingStandardCourseDerivationCompleted` | Single batch derivation adopted. |
| Audit | `TeachingStandardCourseDerivationFailed` | Batch rejected, failed, or invalid. |
| Audit | `TeachingStandardLibraryActivated` | Business expert activates whole standard. |
| Audit | `TeachingStandardLibrarySuperseded` | Standard marked superseded. |
| Failure | `major_identity_missing` | Standard identity cannot be established. |
| Failure | `occupation_orientation_missing` | Required occupation-facing section/table missing. |
| Failure | `core_course_table_missing` | Core-course table not found. |
| Failure | `core_course_row_incomplete` | Required core row cell missing/unmergeable. |
| Failure | `course_duplicate` | Duplicate source course retained once. |
| Failure | `course_non_course_item_excluded` | Explicit non-course item discarded. |
| Failure | `batch_derivation_schema_invalid` | Batch output does not match schema. |
| Failure | `batch_derivation_evidence_invalid` | Batch output lacks source evidence. |
| Failure | `hour_rule_validation_failed` | Suggested-hour constraints fail. |

The final enum names are frozen in Slice 1 with migrations and must not be
introduced into runtime code during Slice 0.

## Corpus Matrix

| Case | Source/fixture | Required assertions |
| --- | --- | --- |
| Higher vocational | `docs/samples/（高职电子商务专业教学标准）电子商务专业教学标准-高等职业教育专科.pdf` | Identity, occupational orientation, all three groups, hour rules, core rows. |
| Secondary vocational | `docs/samples/（中职电子商务专业教学标准）电子商务专业教学标准-中等职业教育.pdf` | Education-level rule variance, foundation/extension lists, excluded practice items. |
| Vocational undergraduate | `tests/fixtures/teaching_standard_course_library/slice0_contract_corpus.json` | Minimum total hours, 60% practice rule, advanced complexity band. |
| Cross-page core row | Existing `CROSS_PAGE_ROW_TABLE` fixture in `tests/test_teaching_standard_graph.py`. | One course row, merged task/requirement evidence. |
| Duplicate course | `tests/fixtures/teaching_standard_course_library/slice0_contract_corpus.json` | One course retained and `course_duplicate` diagnostic. |
| No explicit tool | `tests/fixtures/teaching_standard_course_library/slice0_contract_corpus.json` | `tool_tags=[无特定工具要求]`; no invented software/platform. |

The vocational-undergraduate fixture and the two synthetic normalized fixtures
are contract cases, not production standards. A real vocational-undergraduate
source must be approved by the business expert before Slice 1 schema
implementation is accepted.

## Slice 0 Exit Criteria

- The 21-field contract and parent-standard lifecycle are unambiguous.
- All planned corpus cases have a real source or an explicitly named fixture.
- No database, API, retrieval, index, worker, or Console code changes exist.
- Data Model, AI Governance, Rule Engine, Version State, and Audit review
  questions can be answered from this contract before Slice 1 begins.
