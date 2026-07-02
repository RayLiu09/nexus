# Course Textbook Governance Rules Task Package

## Task name

Course textbook governance rules, semantic chunks, and Evidence Graph validation.

## Source context

- `ARCHITECT.md`: governance input is `normalized_asset_ref`; `knowledge_chunk.normalized_ref_id` links chunks to normalized refs; Evidence Graph rows are evidence-bound to chunks.
- `SPEC.md`: AI governance uses active rules, Prompt templates, rule guardrails, quality scoring, and traceable chunks for downstream search / QA.
- `docs/course_textbook_governance_rules_design.md`: reviewed course textbook governance design.
- `docs/course_textbook_governance_rules_implementation_plan.md`: implementation plan for `course_textbook`.

## Goal

Make the course resource / textbook asset type usable in the existing governance pipeline with stable classification code `course_textbook`, primary knowledge type `textbook_kb`, semantic chunks, and textbook Evidence Graph build validation.

## Scope

- Governance rules seed content and validation.
- Static rules mirror `config/governance_rules_v2.json`.
- Tests for Excel parsing, rule validation, knowledge emission, semantic chunking, and Evidence Graph persistence.
- Documentation updates under `docs/`.

## Out of scope

- New textbook domain tables.
- New textbook-specific governance Prompt template.
- New RAG backend or external index implementation.
- Frontend changes.
- Automatic mandatory Evidence Graph build.

## Forbidden changes

- Do not introduce enterprise IAM or a custom LLM gateway.
- Do not use raw files, raw JSON, or MinerU raw output as governance input.
- Do not introduce `program_profile` as a governance classification code.
- Do not add reverse pointers such as `asset.current_version_id` or `asset_version.normalized_ref_id`.

## Deliverables

- `course_textbook` rules and seed validation.
- `textbook_kb` mapping for course textbook assets.
- Semantic chunk and Evidence Graph tests for textbook assets.
- Verification evidence from focused pytest commands.

## Acceptance

- Rules config validates with `GovernanceRulesConfig`.
- `course_textbook` maps to `textbook_kb`.
- `textbook_kb` produces `SEMANTIC_BLOCK` chunks with locator/source block provenance.
- `graph_profile=textbook` selects full normalized-ref semantic chunks and persists evidence-bound graph rows.
