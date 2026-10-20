# Major Profile Document View Retirement

- **Source context**: `ARCHITECT.md` normalized-document and knowledge-pipeline boundaries; `SPEC.md` Asset Center; Prototype v2.2 IA-7; user decision on 2026-10-20.
- **Goal**: Browse all catalog-visible professional-introduction documents and retain generic RAG access without requiring a fixed profile schema.
- **Scope**: Pipeline A profile projection, major-profile knowledge type, Asset Center list API and UI, historical derived-data cleanup, focused tests and contract docs.
- **Out of scope**: Changes to other document classifications, raw files, normalized source bodies, and unrelated institutional statistics.
- **Forbidden changes**: Do not weaken governance decisions, expose review-only documents through open APIs, or delete raw/normalized source evidence.
- **Acceptance**: The card and unfiltered list count the same assets. Each row shows professional name, code, institution and education level, with a Drawer to edit and audit those metadata fields. Each row also offers parsed preview, RAG chunks and original download. New processing writes no major-profile domain rows or section-derived chunks. Migration removes historical profile projections and their derived chunks while preserving source and audit records.
- **Review gate**: API contract, data cleanup and P0 UX review before rollout.

## Rollout Order

1. Stop old API/Worker processes and finish or park active jobs. The development database had four actively heartbeating jobs during preparation.
2. Deploy the new code artifacts without starting old processes, then run Alembic revision `20261020_0119`. The migration archives the previous active rule version, stores historical identity metadata, removes profile domain rows and old section chunks/manifests, and queues knowledge continuations for current available, index-admitted documents.
3. Start the new API and Workers so they load the updated active rules. Check queued continuation jobs, RAG chunk counts, Asset Center count/list equality, and metadata edit audit entries. Source objects and immutable governance/audit rows are retained.

Pre-migration development inventory: 133 `major_profile` rows, 250 `major_profile_knowledge` chunks, and 57 index manifests. The Asset Center count moved from 87 to 84 during active Worker processing; the new document list and overview both returned 84 in the same verification window.
