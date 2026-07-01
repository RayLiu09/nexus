# Task Package: Evidence-grounded KG Extractor v1

## Source Context

- `docs/evidence_grounded_kg_implementation_plan.md`: Task Package C requires `BodyLLMExtractor`, `TableRowPolicyExtractor`, `MetricImageExtractor`, `DefinitionBodyExtractor`, `SopStepExtractor`, and candidate schema validation.
- `docs/evidence_grounded_knowledge_graph_design.md`: `anchor_role=body` must use LLM schema extraction; rules can only pre-filter or post-validate body content.
- `nexus-app/nexus_app/evidence_graph/candidates.py`: Task Package B provides full normalized-ref candidate chunks and extractor route hints.

## Goal

Add the first extraction layer that converts selected chunk candidates into validated intermediate graph fact candidates. The extractor layer must not write official graph rows; merge, evidence binding, quality gates, and persistence remain later slices.

## Scope

- `nexus-app/nexus_app/evidence_graph/schemas.py`: validated intermediate graph fact schemas and extraction summaries.
- `nexus-app/nexus_app/evidence_graph/extractors.py`: LLM and rule extractor implementations plus router.
- `nexus-app/tests/`: unit tests for schema validation, LLM body extraction, invalid output rejection, rule extractor behavior, and body-LLM enforcement.
- `docs/evidence_grounded_kg_implementation_plan.md`: mark Task Package C as started.

## Out Of Scope

- Build-scope entity merge.
- Relation normalization.
- Evidence binding into `knowledge_graph_evidence`.
- Graph quality gate and official graph table persistence.
- Internal API and Console views.
- Production Prompt profile management for graph extractors.

## Forbidden Changes

- Do not persist extractor output directly to `knowledge_graph_*` tables.
- Do not let `anchor_role=body` use a rule extractor as a substitute for LLM schema extraction.
- Do not call raw files, raw JSON, or MinerU raw output from the extractor.
- Do not change Pipeline B capability graph staging.

## Deliverables

- `GraphFactCandidate` intermediate schema.
- `GraphExtractionResult` with accepted/rejected counts and reject reasons.
- Extractor implementations:
  - `BodyLLMExtractor`
  - `DefinitionBodyExtractor`
  - `SopStepExtractor`
  - `TableRowPolicyExtractor`
  - `MetricImageExtractor`
  - reserved basic `ChartFactExtractor` / `SemanticImageExtractor`
- `extract_graph_candidates(...)` router.

## Acceptance

- Valid LLM JSON produces accepted `GraphFactCandidate` objects.
- Invalid LLM JSON or schema-invalid candidates are rejected with `schema_invalid`.
- `anchor_role=body` without LLM is rejected and does not fall back to rules.
- `table_row` and `metric_image` rule extractors produce evidence-bearing candidates.
- Extraction output includes `source_chunk_id`, `profile`, `anchor_role`, `extractor_name`, `extraction_method`, `evidence_text`, and confidence.
