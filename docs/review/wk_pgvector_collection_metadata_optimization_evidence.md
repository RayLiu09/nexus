# pgvector collection routing and metadata optimization evidence

## Scope and authority

- Actual database: `10.100.11.182:5432 / nexus_dev`; PostgreSQL 18.6, pgvector 0.8.4, actual embedding `bge-m3:latest`, 1024 dimensions.
- User approved collection routing, metadata slimming with normalized copies and source tracing, and retirement of structured-only semantic projections. No partitions or re-embedding. Old API/Worker services will be upgraded after optimization.
- User decision on 2026-11-18: historical metadata snapshots need not be preserved when inconsistent; normalized governance/quality/lineage are authoritative. Formal governance records and source assets are never overwritten by vector maintenance.
- Human Data Model / Semantic Retrieval Integration / Permission And Audit / API Contract Review Gates remain required before merge. No merge or service deployment is included here.

## What the inconsistencies mean

An initial 100-row sample had seven divergent governance snapshots on six normalized refs. All lacked three later-added fields: `classification=industry_regulation_standard`, `classification_name=行业法规标准`, and `classification_confidence=0.96`. Actual `governance_result` history and audits identify the November 2 `regulation-standard-repair` operation, which appended official classifications and updated normalized refs without updating old vector snapshots.

The 1000-row sample found 41 governance differences and six quality differences across 27 refs. Governance differences also included `graph_profile=policy_document`; quality differences included obsolete `major_profile` blockers, `manual_review_status=required` versus current `not_required`, and old anomaly lists versus current empty lists. No lineage difference was observed in this sample; it is not a whole-table equality claim.

| Consumer | Actual source | Impact and treatment |
| --- | --- | --- |
| Vector score and ranking | Stored embedding and distance | Nested classification/name/confidence do not enter the distance calculation. Vectors are unchanged. |
| Public document resource-type/domain filters | Latest official `governance_result` via `classification_for()` | Uses the official classification, not the stale vector snapshot. |
| pgvector collection and row selection | Collection registry and vector filter columns | Full column inventory found 10,714 regulatory vectors / 68 refs and 816 policy vectors / 18 refs still in the research collector. Canonical-domain routing now admits those legacy collectors and applies a matching normalized-ref predicate before Top-K; existing explicit legacy KB calls still work. |
| Search/QA source tracing | `knowledge_chunk` → `normalized_asset_ref` → `asset_version` → `raw_object` | Original file, version, asset, page locator and source blocks do not depend on these three stale classification keys. Batch hydration also restores canonical lineage. |
| Built-in QA grounding | Chunk content, chunk/ref IDs, score | The stale classification keys are not direct grounding inputs. Source metadata is nevertheless forwarded and must remain available. |
| Public tool payload handling | Recursive metadata forwarding and `safe_data()` | `governance.level` is consumed for restricted-subtree hiding. Do not classify all governance as unused. Current normalized values and asset classification/level/tag/org mirrors are hydrated before return. |
| Console governance/quality/graph display | Canonical normalized refs, official results and AI runs | These fields are used, but the screens read their canonical APIs rather than vector snapshots. Clearing obsolete vector quality blockers does not alter admission or version state. |

The P0 permission hook remains its existing identity function; this change does not claim to implement organization-based authorization.

## Implementation and maintenance contract

- Resolve active eligible collection IDs by model, dimension and distance metric. Preserve mandatory ref/chunk intersections. The bounded ID probe freezes the complete eligible small pool for exact ranking; a full probe falls through to the unrestricted scoped pool with HNSW-compatible ordering. This prevents PostgreSQL from computing distances for unrelated legacy-collection rows before applying canonical-domain eligibility.
- A private marker replaces the three redundant normalized snapshots. Batch hydration returns their current canonical values and refreshes their small asset governance mirrors. Unknown metadata, locators, source blocks, IDs, embeddings and hashes stay intact. Missing canonical sources fail closed at read time; missing copies are not removed.
- Structured-only types: `structured_record_table`, `job_demand`, `major_distribution`, `competency_analysis`, `enterprise`, `industrial_park`, and normalized records. Textbook, standard, major-profile and training-plan narrative complements remain eligible.
- Maintenance is audited, idempotent, restartable and bounded. PostgreSQL transforms metadata server-side without transporting multi-GB JSON to the client. Canonical refs use shared row locks while an update commits.
- The metadata GIN index made metadata updates non-HOT, causing expensive HNSW insertions although vectors were unchanged. A 100-row write timed out and rolled back. A committed 10-row pilot then verified SQL/Python equivalence and unchanged vector/projection hashes.
- The authorized index maintenance window saves exact HNSW/GIN definitions before dropping them concurrently, retains B-tree indexes, serializes ownership with an advisory lock, and restores the saved definitions on exit. Process handoffs reuse the durable recovery report.
- UUID ordering caused random TOAST reads. Normalized-ref ordering improved locality but remained I/O bound. The physical runner fixes an initial upper block, processes disjoint bounded ranges with at most eight database workers, checks the 1000-row batch bound, and advances a durable cursor only over contiguous committed ranges. Source rows and embedding columns are never updated.
- A second actual-database pilot verified all 188 rows in 16 heap blocks: SQL/Python metadata equivalence, canonical hydration, and unchanged vector/projection hashes. Updated compact rows may move past the fixed initial bound; final verification must confirm no remaining old snapshots.

## Verification already completed

- App index/pipeline/retrieval suite after canonical hydration and legacy-domain routing: **826 passed, 12 intentionally skipped**.
- Final focused index suite, including conservative parallel resume and recovery-DDL validation: **45 passed**.
- After the final PostgreSQL candidate-ID optimization, the affected index/indexer/metadata/maintenance suite reran: **36 passed**. The new route-index migration passed SQLite upgrade/downgrade verification; the actual PostgreSQL index definition and validity match its idempotency guard.
- API search/QA/evidence/router/audit/scope suite: **59 passed**. After refreshing asset mirrors, the affected search/QA subset reran: **14 passed**.
- Four parameterized public-search cases compare complete results before/after compaction, allowing only approved current-governance values. They assert raw-object ID/URI, version, asset, normalized ref, chunk, locator and source blocks, including L2/L3 handling.
- Actual SQL/Python equivalence and unchanged projection hashes: 10-row and 188-row committed pilots.
- Compilation and `git diff --check` passed. The retrieval golden duplicate fixture now uses same-duration offerings, matching the existing duration-aware identity contract; no production offering logic changed.
- Before the last routing compatibility addition, actual hot plans used B-tree/exact for policy and talent reports, HNSW for course standards, textbooks and research. Initial cold wall times were much larger than hot EXPLAIN times. Final plans must be rechecked after index restoration; no end-to-end latency multiplier is claimed from hot plans alone.

## Database execution status

- Retired-data cleanup committed: **29 vectors**, **one empty collection**, **one index manifest marked stale**. Normalized ref, source chunks and domain facts retained. Post-cleanup inventory: **276,812 vectors / 10 collections**, zero retired projections.
- **Database transactions completed and committed:** all **276,812 surviving projections** compacted across **2,385 audited batches**; **13,046 divergent fields** reconciled to current normalized values. No divergent governance/quality/lineage snapshot was retained. Small asset governance mirrors are refreshed from the canonical value before returning results.
- Audited JSON text size for these projections: **16,069,114,093 → 357,158,094 bytes**, a **97.7774% reduction** (14.97 GiB → 340.61 MiB). This is logical JSON text, not allocated relation size.
- Whole-table remaining governance/quality/lineage snapshots: **0 / 0 / 0**. Compact markers: **276,812**; invalid markers and unavailable canonical sources: **0 / 0**.
- Whole-table metadata ref/asset/version/chunk identity mismatches: **0**. Missing chunks, normalized refs, versions or raw objects: **0**. Chunk/ref, ref/version and version/asset relationship mismatches: **0**.
- Sixteen samples spread across UUID prefixes passed current canonical hydration, asset-governance mirror refresh and private-marker hiding. The committed 10-row/188-row pilots and public API tests separately verify unchanged vectors, locators, source blocks and source identities.
- All ten projection-table indexes are valid and ready. Restored HNSW: **2,071,789,568 bytes**; restored metadata GIN: **69,656,576 bytes**. Operationally installed `ix_kep_ref_collection_route`: **2,465,792 bytes**, created concurrently in **0.549 s**. No Alembic revision was stamped and no unrelated migration ran.
- Ordinary main-table `VACUUM (ANALYZE, PROCESS_TOAST FALSE)` completed in **82.739 s**. TOAST cleanup remained with the existing autovacuum. No `VACUUM FULL`, table rewrite, partitions or global setting changes were performed.
- **Allocated relation files did not shrink:** total **12,489,408,512 → 12,718,628,864 bytes** (11.63 → 11.85 GiB, **+218.60 MiB**). Heap grew from **190,832,640 to 599,777,280 bytes** during metadata updates; the old TOAST allocation remains. Final table-with-TOAST is **10,483,286,016 bytes**, indexes **2,235,342,848 bytes**. Vacuum makes cleared pages reusable; logical slimming must not be reported as filesystem space returned. Filesystem reclamation would require separately scoped rewrite maintenance.
- API/Worker rollout remains with the user as agreed. No API/Worker deployment was performed by this task; the upgrade must include the hydration reader/writer. Migration `20261118_0133` was subsequently executed as recorded below.

## Actual routing and search verification

- Policy and regulatory routing admitted both their own active collector and the research collector containing reclassified refs. Textbooks admitted only their eligible collector. `structured_record_table` admitted none. Observed route-only times were **191.89 / 15.12 / 4.281 / 0.002 ms** respectively; these are one-run observations.
- Seven stored-vector cases passed: policy, regulatory standards, talent reports, course standards, textbooks, research and a reclassified regulatory ref still stored in the research collector. They checked canonical-domain eligibility, threshold, hydrated metadata, hidden storage marker, exact ref/chunk self-match and empty wrong-chunk intersection. Policy/regulatory/scoped-regulatory returned the same qualifying count up to Top-K as exact reference checks.
- The first policy plan read **61,404** collector rows and evaluated distances before discarding unrelated records; observed first wall time was **43,475 ms**, subsequent plan execution **1,931.746 ms**. The final ID probe supplied all **852** eligible IDs; the ranking heap scan then read that bounded pool. Its observed plan execution was **7.908 ms**. Large unscoped regulatory/course/textbook/research samples retained HNSW; the explicit 1,536-row ref scope used an efficient B-tree/bitmap exact sort.
- A separate comparison ran the prior and final small-pool implementations against the **same stored vector** and asserted complete API-hit dictionaries equal, including content, scores and hydrated metadata. Policy: **1,388.196 → 109.031 ms**, ten equal hits. Talent reports: **102.039 → 21.950 ms**, ten equal hits.
- Final seven-case search-only wall observations ranged from **19.285 to 246.062 ms**, with route resolution measured separately. They exclude query embedding, reranking, HTTP, generative QA and concurrency. Cache state differed from the cold first policy run; no universal end-to-end speedup multiplier is claimed.
- A 60-second initial whole-table join verification timed out. Verification was split into chunk checks and a deduplicated canonical-ref/version/raw-object link map with bounded session memory and a 180-second read-only statement limit; all whole-table checks then passed. This was a verification-query change, not a data repair.

## Operational evidence locations

Migration follow-up on **2026-11-19 08:53 Asia/Shanghai**: the user explicitly authorized running the migration. Executed the actual Alembic upgrade **`20261117_0132 → 20261118_0133`** against **`10.100.11.182:5432 / nexus_dev`**; read-back confirms `alembic_version=20261118_0133`, matching the repository head. The migration validated the existing covering index. HNSW, metadata GIN and route covering index retained identical OIDs/definitions and remained valid/ready, confirming no rebuild. No metadata backfill or embedding generation reran. This supersedes the earlier pending-migration status for this database; API/Worker deployment is separate.

Runtime reports contain counts, hashes, cursors and index definitions, without raw chunk/document content or credentials:

- `/tmp/nexus-pgvector-cleanup.jsonl`
- `/tmp/nexus-pgvector-metadata-differences.json`
- `/tmp/nexus-pgvector-mismatch-usage.json`
- `/tmp/nexus-pgvector-projection-drift.json`
- `/tmp/nexus-pgvector-compact-pilot.json`
- `/tmp/nexus-pgvector-physical-pilot.json`
- `/tmp/nexus-pgvector-compact-full.jsonl`, `/tmp/nexus-pgvector-compact-by-ref.jsonl`, `/tmp/nexus-pgvector-compact-physical.jsonl`
- `/tmp/nexus-pgvector-app-regression.xml`, `/tmp/nexus-pgvector-api-tests.xml`, `/tmp/nexus-pgvector-trace-tests.xml`
- `/tmp/nexus-pgvector-compact-physical-resume.jsonl`, `/tmp/nexus-pgvector-index-watch.jsonl`
- `/tmp/nexus-pgvector-finish-route-index.json`, `/tmp/nexus-pgvector-finish-vacuum.json`
- `/tmp/nexus-pgvector-final-verification.json`, `/tmp/nexus-pgvector-routing-verification.json`
- `/tmp/nexus-pgvector-search-before-candidate-ids.json`, `/tmp/nexus-pgvector-final-search-verification.json`
- `/tmp/nexus-pgvector-small-pool-equivalence.json`, `/tmp/nexus-pgvector-final-index-tests.xml`
- `/tmp/nexus-pgvector-migration-0133.json`
