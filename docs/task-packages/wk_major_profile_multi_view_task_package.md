# Major Profile Multi-View Task Package

- **Status**: completed
- **Date**: 2026-06-30
- **Source context**:
  - `docs/pipeline_a_major_profile_structured_data_design.md`: `major_profile.v1` may produce multiple profiles from one professional introduction document.
  - `AGENTS.md`: `major_profile` naming, no `program_profile`; console APIs proxy `nexus-api`; chunks remain section-level semantic blocks.
  - User case: asset `2b393cb0-b71b-4cd5-bac4-0594f8a2b81b` contains multiple major introductions but asset detail displayed one profile.

## Goal

Support professional introduction documents that contain one or more majors, and make the asset detail "知识块" tab provide three basic views:

- Chunks knowledge-block view with locator/source preview.
- Directory / structured profile view.
- Major graph view.

## Scope

- Pipeline A `major_profile` extractor/writer compatibility for multiple profiles per normalized ref.
- `nexus-api` internal ref endpoint returns all profiles for a ref, while preserving a single-profile compatibility endpoint.
- Console major-profile asset detail view renders all profiles under a three-view segmented control.
- View switch follows the record detail pattern and stays right-aligned.
- Directory view uses a major selector and renders one selected major at a time.
- Practice-training content is preserved as a single whole text block, not split into item rows.
- Continuation-major extraction preserves each continuation category label and its full content.
- Focused backend tests and frontend typecheck.
- Controlled one-ref backfill script for already processed major-profile refs.

## Out Of Scope

- Manual edit/delete for `major_profile` rows.
- New RAG backend/index implementation.
- Retrofitting already processed assets automatically; existing assets require reprocess/re-normalize to populate newly extracted profiles.
- Changing section-level chunking into per-item chunking.

## Forbidden Changes

- Do not reintroduce `program_profile` naming.
- Do not make console-only routes business-facing APIs.
- Do not bypass `normalized_asset_ref` lineage.
- Do not split semantic chunks by individual bullet/course/certificate item.

## Deliverables

- Multi-profile extractor/writer support.
- Ref-level major profile API returning a list.
- Console "知识块 / 目录 / 专业图谱" views for `major_profile.v1`.
- Tests for multiple profiles under one normalized ref.
- `scripts/rebuild_major_profile_for_ref.py` for controlled local rebuild of derived major-profile rows and section chunks.

## Acceptance

- A normalized ref can own multiple `major_profile` rows.
- Asset detail no longer displays only the first profile when multiple profiles exist.
- Chunks view uses existing chunk preview/locator drawer.
- Directory view lets the user select one extracted profile and renders its sections.
- Major graph view visualizes profile-to-section/item relationships.
- Course graph nodes aggregate under `专业基础课程` / `专业核心课程` / `实习实训`, with `实习实训` kept as one whole content node.
- `接续专业举例` preserves category-level entries such as `接续高职专科专业举例` / `接续高职本科专业举例` / `接续普通本科专业举例`.

## Verification

- `cd nexus-app && uv run pytest tests/test_major_profile.py`
- `cd nexus-api && uv run pytest tests/test_major_profile_api.py`
- `cd nexus-console && npm run typecheck`
- `git diff --check`

Sample backfill verification:

- Asset `2b393cb0-b71b-4cd5-bac4-0594f8a2b81b`, normalized ref `1b2bef04-0c0f-4026-9d7c-609689d87fb3` was rebuilt with:
  - 5 profiles: `730701 电子商务`, `730702 跨境电子商务`, `730703 移动商务`, `730704 网络营销`, `730705 直播电商服务`.
  - 30 section-level chunks, 6 per major profile.
