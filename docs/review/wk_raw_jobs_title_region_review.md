# Raw Job Title And Collection Region Review Evidence

Date: 2026-11-17. Single-agent implementation.

Task: [bounded task package](../task-packages/wk_raw_jobs_title_region_task_package.md).

## Result And Boundaries

- `raw_jobs.title_normalized` is a conservative local cleaned title, independent
  of future job normalization/classification. Raw titles and semantic rank,
  specialty, platform, employment type and compound jobs remain intact.
- `raw_jobs.region` copies upstream collection region verbatim; provenance keeps
  its original query_region and raw_record. No address/geographic interpretation.
- Public list/aggregate and internal list/export use collection region with
  escaped literal substring matching before pagination/grouping/export.
- Responses expose both fields; raw `job_title` stays intact. Text title search
  includes cleaned titles. Export appends two columns without shifting old ones.
- No Pipeline B/governance activation, AI calls, frontend workflow changes,
  new occupation dictionary, reverse pointers or status transitions.

## Data Model Gate Evidence

- Additive migration `20261117_0132`, parent `20261116_0131`, adds nullable TEXT
  title_normalized and VARCHAR(80) region. Downgrade removes only those columns.
- SQLite migration smoke test executes upgrade/downgrade and verifies original
  rows/fields survive. No PostgreSQL deployment or performance claim is made.
- New ingestion retains provider/upstream-record identity and unchanged canonical
  raw hash. Replay creates no duplicates; changed payload is still rejected.
- Existing atomic page/checkpoint, retry/conflict and rollback tests pass.
- Historical repair defaults to dry-run; keyset batches fill only missing
  columns, preserving created_at/updated_at, provenance hashes and receipt time.
  Missing provenance leaves region NULL even with a usable-looking address.

## API Contract And Permission/Audit Gate Evidence

- API tests deliberately disagree collection region and address. Results prove
  main-table region is used, including records without provenance or address.
- Tests cover totals across pages, public full-scope aggregation, internal
  all-matching export, combined conditions, literal percent/underscore and empty
  query validation. NULL region does not fall back to address.
- Public detail/list response schema adds nullable title_normalized and region;
  raw_fields stays source business fields. Existing aggregation whitelist and
  collected_from/to/received_to behavior remain intact.
- Existing public credential-denial/read-audit tests pass. Repair writes one
  attributed audit per changed row, with trace ID, rule version and field names;
  it does not log original titles, addresses or complete payloads.
- Generated public tools match the current OpenAPI and explicitly describe
  region as collection scope, not actual work location.
- ARCHITECT.md, SPEC.md, readme.md, raw-intake contract, public consumption docs
  and the job-normalization design now document the bounded new behavior.

## Verification

From `nexus-app`:

```sh
.venv/bin/python -m pytest tests/data_sync/test_job_title_cleaning.py tests/data_sync/test_job_posting_intake.py tests/data_sync/test_raw_job_backfill.py tests/data_sync/test_raw_job_title_region_migration.py
```

Result: **24 passed**. Includes conservative/idempotent title cases, intake
replay and failed-page behavior, missing region, repair dry-run/replay/resume,
audit attribution, timestamp preservation and migration round trip.

From `nexus-api`:

```sh
.venv/bin/python -m pytest tests/test_raw_jobs_api.py tests/test_agent_public_business.py tests/test_public_function_tools.py
```

Result: **44 passed**. The sandbox attempt stalled in Starlette TestClient's
AnyIO thread startup; it was stopped and the same suite passed outside the
sandbox with in-memory SQLite fixtures. No live business database is used.

From repository root:

```sh
nexus-api/.venv/bin/python scripts/generate_public_function_tools.py
nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check
```

Result: **55 tools generated; artifact drift check passed**.

## Rollout And Review Status

1. Apply `20261117_0132` before starting services with the new ORM model.
2. Preview historical repair from the repository root:
   `nexus-app/.venv/bin/python nexus-app/scripts/backfill_raw_job_title_region.py`.
3. Apply repair with `--apply`, optionally `--batch-size 500` / `--after-id`.
   Repeating it safely skips filled values; each changed batch commits its audits.
4. Restart API/collection workers as part of the ordinary deployment process.

Historical NULL fields stay NULL until repaired and do not match region filters.
The former public address-based region behavior intentionally changes per user
instruction. These fields do not count deduplicated job demands or true workplace
coverage. Initial implementation ran no live migration or backfill; the
authorized local database follow-up below records subsequent database writes.
No service restart or deployment was run.

Implementation and automated evidence are ready for Data Model/API Contract and
Permission/Audit review. Human approval before merge remains governed by
WORKFLOWS.md; this record does not assert human approval.

## Authorized Development Database Update

User requested updating the local database. `.env.dev` identifies the documented
development instance `10.100.11.182:5432/nexus_dev` (not a loopback instance).

- Upgraded `20261030_0129` → `20261117_0132`, reviewing prerequisites:
  `0130` activates an audited rules version without rewriting historical
  results; `0131` adds a tag lookup index; `0132` adds the two nullable job fields.
- Previewed and filled **142,272** historical rows, with both columns populated
  for every row and **142,272** attributed repair audits. There are 35 distinct
  collection-region values, and every region matches provenance.query_region.
- `simple-v1` changed the normalized text of 40,112 titles. Full recomputation
  check found zero mismatches, zero missing fields or missing provenance.
- Before/after original-field row count and order-independent hash summaries
  match, including original titles, addresses, timestamps and all provenance
  fields. No original raw record was changed by the repair.
- Repair now loads only needed columns and bulk-writes updates/audits per
  keyset batch (2,000 for this run). Added failure injection proves audit failure
  rolls back the current batch while retaining the prior committed batch.

## Sample-driven Title Cleaning Follow-up

User reported `广告标识设计师(周末双休+地铁直达)` and
`设计师/插画师(多职级招聘·线上远程协作)接受实习`, then requested rules
based on existing data. Read all 142,272 raw titles and examined frequent bracket
fragments, separated tails and bounded examples. Keyword hits (overlapping):
双休 7,958; 五险 5,437; 底薪 1,660; 远程 408; 地铁 201.

`simple-v2` adds explicit benefit/schedule/commute/salary/acceptance/remote-note
rules, preserves meaningful bracket fragments, and recognizes `J11163`-style
IDs. Actual samples and technical counterexamples are regression cases:

| Source title | Cleaned title |
| --- | --- |
| 广告标识设计师(周末双休+地铁直达) | 广告标识设计师 |
| 设计师/插画师(多职级招聘·线上远程协作)接受实习 | 设计师/插画师 |
| 对公客户经理(合同制+六险二金) | 对公客户经理(合同制) |
| (PS AI)美工平面设计师 可兼职 | (PS AI)美工平面设计师 |
| 运营管理实习生(带薪培训) | 运营管理实习生 |
| 软件工程师(五险一金/C++) | 软件工程师(C++) |
| 平台软件工程师（Agent开发） | 平台软件工程师(Agent开发) |

Formal part-time/internship role labels remain; optional acceptance notes can be
removed. Technical names, direction, ranks, platforms and compound roles are not
replaced with canonical occupations. No LLM or downstream job normalization.

Detected **8,006** salary-first source detail blocks with education/experience
and company text in title_raw. These cannot reliably yield the original job
title by deleting noise; retain basic normalized text for a later source-intake
repair rather than inventing a job name. This count is a heuristic finding,
not a claim of complete source-quality detection.

`--reclean-titles` permits explicit re-computation from title_raw; default
missing-only behavior is preserved. Dry-run, unchanged regions, per-row rule
version audit and repeat execution are tested.

Final `simple-v2` verification and applied development results:

- **78 focused core/intake/repair/migration tests passed**. Previous API/tool
  suite remains 44 passed; this follow-up changes cleaning/repair, not APIs.
- Full preview: 142,272 rows; **22,251** existing cleaned titles differ from
  simple-v1; **zero empty** and **zero non-idempotent** results.
- Applied `--apply --reclean-titles --batch-size 2000`: 22,251 title updates,
  **zero region updates**, with **22,251 simple-v2 audits**. Initial simple-v1
  audit count remains 142,272 (164,523 repair audit records in total).
- Read every stored title after commit: **zero mismatches** against simple-v2.
  Both new fields remain populated on all 142,272 rows; every stored region
  matches its collection provenance. 50,935 cleaned titles differ from title_raw.
- Original raw-field and provenance row counts/hash summaries remain identical
  to the pre-migration baseline, including timestamps. DB revision is
  `20261117_0132`. No service restart or deployment was performed.
- Sample findings establish coverage of reviewed explicit noise, not perfect
  linguistic classification. Ambiguous fragments and sources without a reliable
  job title still require source-quality correction; no inferred occupations.
