# Task Package: Asset Detail Specialized View Retirement

## Status

Complete.

## Goal

Remove obsolete domain presentation from the technical Asset Detail while
preserving generic knowledge chunks and the Asset Center ownership boundary.

## Frozen Contract

- Professional teaching-standard Asset Detail keeps its filtered knowledge
  chunks but no longer offers or loads the `目录` view.
- Course-standard Asset Detail may continue to offer its existing course
  knowledge graph; this task does not remove that separate classification.
- Job-demand record Asset Detail does not expose the `结构化图谱` tab and does
  not import, request, or render the job-demand specialized view.
- Generic record fallback, lineage, governance, quality, and version views are
  unchanged.
- Job-demand domain data, APIs, and reusable components remain available for a
  future Asset Center business view.

## Scope

- Retire teaching-standard directory UI, content fetch, resolver, and tests.
- Extend the existing Asset Detail structured-view visibility policy to job
  demand and remove its specialized dispatcher dependency.
- Add focused policy tests and optional real-asset E2E checks.
- Update architecture, product, prototype, and repository contracts.

## Out Of Scope

- Backend, database, normalized-document, governance, or extraction changes.
- Building the Asset Center job-demand business view.
- Removing course-standard graphs or generic RAG chunks.
- Deleting job-demand data APIs or graph projection code.

## Acceptance

- A professional teaching-standard knowledge view contains no `目录` control
  and makes no normalized-content request for directory construction.
- A job-demand technical asset detail contains no `结构化图谱` tab.
- Major-distribution and ability-analysis structured views remain hidden;
  generic record assets retain their existing structured fallback.
- Focused Vitest, TypeScript, scoped ESLint, desktop E2E, and
  `git diff --check` pass. Production build is attempted and any external
  dependency outage is recorded separately from source verification.

## Review Gates

- **UX Boundary Gate**: technical Asset Detail no longer duplicates the two
  retired domain presentations.
- **Regression Gate**: course-standard graph and generic record behavior remain
  available.
- **Acceptance Gate**: source, tests, and root/product/prototype contracts agree.

## Verification Evidence

- Focused Vitest: 3 files, 28 tests passed.
- TypeScript: `pnpm exec tsc --noEmit` passed.
- Scoped ESLint: changed TypeScript, TSX, and E2E files passed.
- Real-data Playwright: professional teaching-standard and job-demand Asset
  Detail checks passed in desktop Chromium (2 tests).
- `git diff --check` passed.
- `pnpm build` was attempted both in the sandbox and with network access. Next.js
  stopped while fetching `Inter Tight` and `JetBrains Mono` from
  `fonts.googleapis.com`; it reported no source or TypeScript compilation error
  before that external network failure.
