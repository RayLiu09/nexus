# Task Package: Parsed Preview Images

## Goal

Rename the normalized-document preview to "解析预览" and display retained source images with their normalized blocks.

## Scope

- Rename the shared preview entry points and preview panel; keep raw-object download separate.
- Expose a user-authenticated internal image read by normalized ref, block ID, and image index. Validate the image against the normalized block and its version-scoped parsed path.
- Place extracted images after the corresponding Markdown block without rewriting `body_markdown` or block ranges.
- Cover image success, invalid ownership/index, missing storage, and preview rendering with focused tests.

## Out Of Scope

- Reprocessing assets, changing MinerU extraction, governance rules, retrieval content, or raw object state.

## Forbidden Changes

- Do not expose arbitrary object-storage keys or public image URLs.
- Do not use raw files as governance inputs.
- Do not mutate stored normalized payloads or locators.

## Review Gates And Acceptance

- API Contract / Frontend UX Gates: existing normalized content contract remains intact; the new binary read requires console user auth and only serves images referenced by the requested ref/block.
- The white-paper chart `图1-3` appears in 解析预览 using the stored image after its caption, while 原文下载 still opens the original PDF.
- Missing images show a local failure state and leave text readable.
- Backend and Console focused tests, typecheck, and lint pass.

## Review Evidence

- `nexus-api`: `uv run pytest tests/test_internal_chunk_preview.py -q` passed (10 tests), including block ownership, version path, missing object, and unauthenticated access.
- `nexus-console`: focused `SourcePreviewSection` tests passed (2 tests); `npm run typecheck` passed. Focused ESLint exited without errors; the component retains one pre-existing `react-hooks/set-state-in-effect` warning.
- The retained `2025直播电商行业发展白皮书.pdf` chart block `block-p17-047` returned a 54,648-byte JPEG through the new read logic. The restarted local API advertises the route, and the Console proxy returns 401 without a login cookie.
