# Major Profile API And Console Task Package

- **Status**: completed
- **Date**: 2026-06-30
- **Source context**:
  - `docs/pipeline_a_major_profile_structured_data_design.md`: reviewed `major_profile.v1` design and section-level chunking contract.
  - `docs/task-packages/wk_major_profile_task_package.md`: backend extraction/domain-table/chunk implementation baseline.
  - `AGENTS.md`: business-facing APIs belong in `nexus-api`; console APIs remain control-plane proxies; no new RAGFlow dependency.

## Goal

Expose processed Pipeline A `major_profile` assets through read APIs and render them in the asset detail page as a structured professional profile view.

## Scope

- `nexus-api` read-only internal/open endpoints for `major_profile`.
- `nexus-console` API proxy routes for console consumption.
- Asset detail structured view for `metadata_summary.domain_profile == major_profile.v1`.
- Tests for API filtering and serialization.

## Out Of Scope

- Manual edit/create/delete for `major_profile` rows.
- New RAG backend selection or index adapter implementation.
- Reworking the extraction algorithm shipped in the previous task.
- Cross-domain merge with `major_distribution`; future query views may join on `major_code`.

## Forbidden Changes

- Do not expose console-only APIs as business-facing APIs.
- Do not return non-available assets from open APIs.
- Do not bypass `normalized_asset_ref` / `asset_version` state gates.
- Do not split major profile semantic chunks by individual bullet items.
- Do not reintroduce `program_profile` naming.

## Deliverables

- `/internal/v1/major-profiles` list/detail/ref endpoints.
- `/open/v1/major-profiles` list/detail endpoints.
- Console proxy under `/api/major-profiles`.
- Asset detail `MajorProfileKnowledgeView` displaying structured profile sections.
- Focused API tests.

## Acceptance

- Profiles are queryable by `major_code`, `major_name`, `occupation`, and `education_level`.
- `GET /internal/v1/normalized-refs/{ref_id}/major-profile` returns profile detail for the asset detail page.
- Open APIs return only profiles anchored on `available` versions.
- Asset detail renders major profile sections instead of generic record fallback text.

## Verification

- `cd nexus-api && uv run pytest tests/test_major_profile_api.py tests/test_major_distribution_api.py`
- `cd nexus-console && npm run typecheck`
