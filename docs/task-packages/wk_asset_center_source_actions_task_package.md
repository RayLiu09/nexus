# Task Package: Asset Center Source Actions

## Status

Implementation and automated verification complete; Frontend UX Gate awaits human review.

## Source Context

- `AGENTS.md`, `WORKFLOWS.md`, `SPEC.md`, and Prototype v2.2 define Asset Center ownership and Drawer behavior.
- Existing teaching-case and major-profile lists provide parsed preview, RAG chunks, and original download patterns.

## Goal

Expose parsed preview, RAG chunks, and original download on course-textbook rows, and original download on occupational-ability analysis rows.

## Scope

- Add `raw_object_id` to the two internal paginated list responses using their selected asset versions.
- Add the requested row actions, reusing existing preview, chunk, and download endpoints.
- Make the occupational-ability graph Drawer and canvas follow viewport width and height.
- Update focused API and Console tests and the affected product documentation.

## Out Of Scope

- Public API, governance, indexing, parsing, data-model, or permission changes.
- New technical asset-detail entry points or changes to existing outline and ability views.

## Forbidden Changes

- Do not derive the download target from a different asset version or raw lineage text.
- Do not load preview or chunks during list rendering.
- Do not introduce redundant reverse pointers or new business-facing APIs in Console.

## Acceptance And Review Gates

- API Contract Gate: both list rows carry the selected version's raw object ID; existing pagination and fixed query count remain intact.
- Frontend UX Gate: requested actions appear on each applicable row; preview and chunks open lazily in a Drawer, download handles missing IDs and errors, and the graph viewport resizes with the window.
- Verification: focused backend and frontend tests, typecheck, lint, and diff check pass.

## Verification Evidence

- API Contract Gate: 13 focused tests passed, including direct source-version ID assertions and the existing constant-query-count check. The ASGI client tests required running outside the filesystem sandbox.
- Frontend UX Gate: 8 focused component tests passed for conditional actions, lazy Drawers, source download, and graph viewport configuration.
- Console typecheck, scoped Prettier check, and `git diff --check` passed.
- Scoped ESLint could not start because the existing `eslint.config.mjs` imports an uninstalled `eslint-plugin-testing-library` package.
- The Console dev server responds on port 3002. Browser review with live analysis data remains the human Frontend UX Gate.
