# Task Package: collection routing, compact vector metadata and retired projections

## Source context

- User authorization (2026-11-18): add collection routing, slim metadata only when the removed values remain readable on normalized assets, preserve retrieval, and clean obsolete structured-only collections such as `structured_record_table`; no partitioning.
- `ARCHITECT.md`: vectors are replaceable projections anchored by normalized refs/chunks; domain tables own structured retrieval.
- `SPEC.md`: preserve search/QA scopes, source citations, governance/permission checks and audit.
- `WORKFLOWS.md`: bounded single-Agent implementation; Semantic Retrieval, Permission/Audit and API compatibility review before merge.

## Goal and scope

- Resolve eligible collections by model/dimension/metric and business scope before vector ranking, including broad fallback.
- Write compact metadata and batch hydrate omitted normalized-ref fields on search; support existing full metadata throughout rollout.
- Provide resumable, dry-run-first maintenance with per-row canonical-source checks, bounded transactions and audited apply; retain unknown fields and snapshots lacking a canonical source. Discard divergent governance/quality/lineage snapshots as explicitly approved by the user.
- Establish an explicit structured-only retirement policy from current domain contracts; block recreation and exclude retired projections from retrieval; clean only their vectors and collection registry rows.
- Cover adapter/indexer/maintenance behavior with focused tests and PostgreSQL read/plan evidence where available.
- Update architecture/spec/README and review evidence.

## Forbidden and out-of-scope changes

- No partitions, new vector engine, model changes/re-embedding, global database tuning, or frontend/API schema change.
- Never delete source assets, normalized refs, domain facts or canonical governance/quality/lineage.
- Do not retire narrative semantic complements merely because their asset also has domain tables (e.g. training plans, standards and textbooks).
- No new reverse pointers, IAM/gateway/MQ infrastructure or AI governance changes.
- No raw content, vectors or credentials in logs/review artifacts.
- Reader rollout: the user explicitly confirmed that old API/Worker services will
  be upgraded after this optimization; deliver hydration-compatible code and
  apply the authorized maintenance to `10.100.11.182 / nexus_dev` accordingly.

## Acceptance and rollout

- Collection filtering precedes Top-K; model/dimension/metric separation and mandatory ref/chunk intersections remain intact.
- Legacy and compact metadata return the existing metadata shape with a bounded number of batch reads; missing canonical data fails closed rather than silently losing fields.
- User decision (2026-11-18): discard inconsistent historical snapshots and hydrate current canonical normalized-ref governance/quality/lineage. Count reconciled fields, retain unknown projection fields, and require a non-null normalized source before removal. Trace identities, locator and source blocks must remain unchanged.
- Retrieval golden fixtures must use same-duration major-offering duplicates,
  consistent with the existing duration-aware identity contract; no domain
  intake behavior changes are included.
- Maintenance is idempotent, bounded, restartable, auditable and reports counts/bytes without content.
- Only explicitly retired structured-only types are deleted; semantic complements remain queryable.
- Run focused unit/API regressions, inspect actual PostgreSQL plans and dry-run inventory. Apply authorized maintenance with the user's coordinated reader upgrade, then verify counts and copied-field preservation.
- Human Review Gates are required before merge. The user's 2026-11-19 follow-up authorizes committing and pushing this task's changes; no service deployment is included.

## Actual-database maintenance window

- A 10-row committed pilot verified unchanged vector/projection hashes, SQL/Python compaction equivalence and canonical hydration. A 100-row update previously timed out and rolled back.
- `ix_kep_metadata_gin` makes metadata updates non-HOT, requiring HNSW insertions even when vectors are unchanged. Actual statistics showed zero HOT updates. Row-by-row HNSW maintenance is unsuitable for the full backfill.
- Explicit `compact --apply --rebuild-projection-indexes --report-file ...` temporarily drops only the existing HNSW and metadata GIN indexes concurrently, commits bounded metadata updates, then rebuilds their exact saved definitions concurrently. B-tree routing indexes remain present. This is a maintenance window: ANN performance is reduced until HNSW restoration completes. The user will upgrade API/Worker services after optimization.
- Save index definitions to the durable report before DDL, serialize maintenance with a session advisory lock, restore indexes on normal completion and exceptions, and verify both indexes valid afterward. Process termination outside Python cleanup requires running the saved `CREATE INDEX CONCURRENTLY` definitions after removing any invalid leftover index.
- No embeddings are recomputed; no asset/chunk/domain/source data is deleted; no table rewrite, partitioning, `VACUUM FULL` or global setting change is included.
- Actual heap/TOAST I/O requires a physical-range backfill for this database. `compact_pgvector_physical.py` fixes an upper block before work, bounds each transaction to 1000 rows, supports disjoint database workers, conservative contiguous resume, and bounded retries for transient waits. The report and final full-table remaining-snapshot check are required.
- Resource inspection found approximately 12 GiB host memory / 5 GiB available and a default 64 MiB index-build budget. Explicit maintenance sessions can use a reviewed 2 GiB private build budget with parallel maintenance workers disabled; batch sessions use bounded work memory. These do not alter global settings or the saved index definitions.
- Migration `20261118_0133` adds `(normalized_ref_id, collection_id, knowledge_type_code)` for index-only legacy routing. Apply this single index operationally after backfill, without stamping revisions or executing unrelated migrations; application upgrade later runs the idempotent migration. Include Data Model Gate in the merge review.

## Execution result (2026-11-18)

- Authorized database work completed: 276,812 surviving projections compacted; 13,046 divergent fields reconciled; 29 retired projections and one empty collector removed. Three old snapshot counts, missing canonical copies and source-anchor mismatches all verified zero.
- HNSW and metadata GIN restored valid/ready; route covering index installed valid/ready. Ordinary main-table VACUUM/ANALYZE completed. No Alembic stamp, unrelated migration or service deployment.
- Logical JSON text fell 97.7774% (16,069,114,093 to 357,158,094 bytes). Allocated relation files remain 11.85 GiB versus 11.63 GiB initially; physical file reclamation is outside this task.
- Final small-pool ranking uses all eligible IDs returned by the bounded probe before computing distances. The overflowing probe does not limit the larger ANN pool. Seven actual stored-vector cases and two complete old/new response comparisons passed.
- Review evidence: `docs/review/wk_pgvector_collection_metadata_optimization_evidence.md`. Human gates remain before merge; API/Worker upgrade must include these changes and migration `20261118_0133`.

## Migration follow-up (2026-11-19)

- At the user's explicit instruction, executed the real Alembic upgrade on `10.100.11.182:5432 / nexus_dev` from `20261117_0132` to `20261118_0133`; verified the stored revision now matches the repository head.
- Existing HNSW, metadata GIN and route covering indexes retained their OIDs/definitions and remain valid/ready. No index rebuild, repeated backfill or embedding generation. API/Worker deployment remains separate.
- Execution evidence: `/tmp/nexus-pgvector-migration-0133.json` and the review evidence's migration follow-up.
