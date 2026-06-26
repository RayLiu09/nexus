# Pipeline B Major Distribution Task Package

- **Status**: implementation in progress
- **Date**: 2026-06-26
- **Source context**:
  - `AGENTS.md`: Pipeline B record assets must use `ingest_validate -> assetize -> normalize`, governance input must be `normalized_record` via `normalized_asset_ref`.
  - `docs/pipeline_b_major_distribution_structured_data_design.md`: PD0-PD3 implementation slices.
  - `docs/pipeline_b_contract_freeze.md`: existing Pipeline B profile/record-body/domain table conventions.

## Goal

Implement Pipeline B support for major distribution tables (`major_distribution`) using the two sample Excel files under `docs/samples/`, including profile detection, record-body projection, domain tables, writer dispatch, and read APIs.

## Scope

- `nexus-app` profile detection, record-body projection, domain models, Alembic migration, writer, and tests.
- `nexus-api` read-only open/internal APIs for major distribution datasets and records.
- Governance rules seed/code alignment already started in `config/governance_rules_v2.json` and `seed_data.py`.

## Out Of Scope

- MinerU / Pipeline A parsing.
- RAGFlow chunking or `knowledge_chunk` generation for this record type.
- Frontend custom table view beyond classification label compatibility.
- Education ministry major-catalog validation.

## Forbidden Changes

- Do not introduce `asset.current_version_id` or `asset_version.normalized_ref_id`.
- Do not bypass `governance_rule_version` for classification, level, tags, quality, or admission.
- Do not persist summary rows as domain records; `全部` / `全国` / `合计` rows are ignored and counted.
- Do not infer `education_level` without explicit evidence.

## Deliverables

- `major_distribution_dataset` and `major_distribution_record` tables.
- `major_distribution.v1` profile detection and record-body projection.
- Domain writer with idempotent delete/reinsert semantics.
- Read-only `/open/v1` and `/internal/v1` APIs.
- Focused tests for both supplied Excel samples and writer/API behavior.

## Acceptance

- `docs/samples/2.（专业布点数）专业布点数.xlsx` detects as `major_distribution_dataset` and projects 2 records plus 1 placeholder.
- `docs/samples/电子商务专业布点数量.xlsx` detects as `major_distribution_dataset`, projects 32 detail records, and reports `ignored_summary_count = 1`.
- Domain writer persists records idempotently and ignores summary rows.
- Existing `governance_rules_version` content and new seeds use `major_distribution`, not `program_distribution`.
