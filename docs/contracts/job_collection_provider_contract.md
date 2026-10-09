# Job Collection Provider Contract (C1)

Status: OpenAPI schema baseline, inspected 2026-10-08, with C2 live verification recorded in `docs/review/job_collection_c2_live_verification.md`. The adapter and raw job intake are implemented; the default Catalog keeps the real Provider disabled until a private deployment Catalog is selected. Source: live `Job Collection Engine API` OpenAPI `0.2.0` at `http://10.100.11.51:8080/openapi.json`.

## Ownership And Boundaries

- NEXUS uses one deployment-owned `crawler_engine` Provider definition. Its `api_server_url` is `http://10.100.11.51:8080` and its configured `tenant_id` is `upstream-application-a`; the Catalog also holds `tenant_name` and a private `tenant_key`. The live Token API request schema contains `tenantKey` only, so the adapter does not send `tenant_id` in that request. The real key is never committed, returned, logged, or stored in a sync plan or run. `DATA_SYNC_PROVIDER_CATALOG_PATH` selects the private deployment Catalog.
- The adapter owns all `/v1/...` paths, request/response mapping, query schema, fixed source protocol, and external status mapping. Plans hold only frequency and business query parameters. Initial source support in the live schema is `zhaopin`.
- `data_sync_run` remains the collection control-plane record. The result receiver persists `raw_jobs` and one-to-one `raw_job_provenance` before advancing the page cursor. No sync batch or observation table is introduced.
- Later job cleaning, demand identity, extraction, clustering, and dictionary work use independent snapshot-based domain objects. They do not require Pipeline B `normalized_record` / `normalized_asset_ref` or generic AI governance.

## Verified Wire Schema

| Operation | Request | Success response |
| --- | --- | --- |
| `POST /v1/auth/token` | JSON `{ "tenantKey": "<private>" }`; OpenAPI also permits null, but NEXUS must send a nonempty key. | 200: `accessToken` (string), `tokenType` (`Bearer`), `expiresIn` (positive seconds), `scopes` (array). |
| `POST /v1/collection-jobs` | Bearer token; optional `Idempotency-Key` header; JSON requires `source`, `queries`, `externalRequestId`. Optional `schemaVersion=1`, `collectionMode=full|incremental`, scalar `metadata`, `callback`. | 202: `collectionJobId` (UUID), `externalRequestId`, `status=queued`. |
| `GET /v1/collection-jobs/{job_id}` | Bearer token and UUID Job ID. | 200: Job ID, request ID, source, desired state, status, version, task counts, `processedCount`, failure-code counts, timestamps. |
| `POST /v1/collection-jobs/{job_id}/{action}` | Bearer token; action is `pause`, `resume`, or `cancel`. | 200: full Job response. OpenAPI declares no idempotency-key parameter here. |
| `GET /v1/collection-jobs/{job_id}/records` | Bearer token; opaque `cursor` (max 512 chars); `limit` 1-200, default 50. | 200: `items[]`, optional nullable `nextCursor`. |

`CollectionQuery` requires `keyword` (1-120 chars); `region` is optional (max 80, default empty); `pageLimit` is optional (1-30, default 10). A submit request accepts 1-100 queries. NEXUS plans select multiple database-backed job names and fixed city options; the adapter expands their Cartesian product into upstream `queries`, with at most 100 combinations. Page choices are 10, 30, 50, and 100 (default 30); 50 and 100 require the planned upstream limit increase before a live run can succeed. The job catalog imports only the name column from `76个岗位.xlsx`: 76 source rows contain 74 distinct selectable names. `source=zhaopin`, `schemaVersion=1`, and callback omission remain adapter decisions. Whether to expose `collectionMode` as a plan parameter requires a separate product decision; default to `full` for the first slice. Derive a stable `externalRequestId` and submit idempotency key from the NEXUS run ID, and reuse them on retry.

Each record has required `recordId`, `taskId`, `source`, `sourceUrl`, `keyword`, `page`, `fields`, `collectedAt`, `payloadHash`, and `createdAt`; `sourceJobId` and `region` may be absent. `fields.title` is required. Optional fields include `companyName`, `addressText`, `salaryText`, `experienceText`, `degreeText`, `hiringText`, `description`, `skillsText`, `jobResponsibilitiesText`, `jobRequirementsText`, `qualificationsText`, `otherMattersText`, `companyIndustryText`, `companyScaleText`, `companyFinancingText`, and `jobTagsText`. Preserve the entire record JSON and source field names. The older normalization design's `responsibilityText`/`requirementText`/`bonusText` names do not match this live schema and need an explicit versioned mapping in the result receiver.

## Status And Control Mapping

Upstream Job status enum: `queued`, `running`, `pausing`, `paused`, `awaiting_human`, `cancelling`, `cancelled`, `succeeded`, `partially_succeeded`, `failed`. Upstream `desiredState` is separately `running`, `paused`, or `cancelled`. Keep these raw statuses in `external_status` / safe status detail; NEXUS run status has only seven stable values.

| Upstream status | Proposed NEXUS behavior |
| --- | --- |
| `queued`, `running`, `awaiting_human`, `pausing`, `cancelling` | Keep the run nonterminal and poll with bounded delay; do not start another external Job. Surface `awaiting_human` in safe status detail. |
| `paused` | Run is paused after external state confirmation. |
| `cancelled`, `failed` | Terminal external state; preserve safe failure summary and any already received raw records. |
| `succeeded`, `partially_succeeded` | Drain all record pages through the receiver, then settle the NEXUS run. Upstream completion alone does not imply records were persisted. |

The current NEXUS run-control contract updates its stable state immediately after a successful synchronous downstream response. C2 verified that `POST /pause` returns HTTP 200 with `status=pausing` and `desiredState=paused`; the Job reached `paused` only on a later read. Therefore HTTP 200 confirms acceptance of the control request, not the external stable state. The NEXUS adapter must inspect the response and keep the run nonterminal until a later status read confirms `paused` or `cancelled`. This requires an API Contract Review Gate before enabling live controls. Do not silently add new NEXUS run statuses or an asynchronous control-request table.

## Result Handoff Contract

- A page is accepted only after every valid raw record has been durably written or identified as an idempotent replay. In the same short database transaction, update the page cursor and accepted/duplicate/invalid counts. External HTTP fetch occurs before this transaction.
- Use the upstream `recordId` scoped by provider as the replay identity; retain `sourceJobId`, `sourceUrl`, and `payloadHash` for source linkage and content-change analysis. A later run can yield a new raw job version with a new record ID for the same source job.
- Preserve the complete upstream record and timestamps. Invalid records remain traceable with bounded error details; they must not be counted as accepted records.
- `nextCursor` is opaque. Continue until null; do not decode, synthesize, or order by `collectedAt`. C2 observed `items=[]` and `nextCursor=null` while the Job was still running with zero processed records. Therefore an empty/null page is final only after the external Job has reached a terminal state and the final records are drained. Final NEXUS run success requires that final page to be persisted.
- The receiver writes one raw job and its provenance per upstream record ID. Later job processing defines its own population for cleaning and demand statistics.

## C2 Verification And Remaining Checks

1. Verified: tenant key exchange returned a Bearer Token valid for 3600 seconds with `collection:write`, `collection:read`, and `collection:control`; an invalid key returned 401 and a malformed auth body returned 422. A restricted-scope 403 was not exercised.
2. Verified: identical submit with the same `Idempotency-Key` and `externalRequestId` returned the same Job ID (202); a changed query with those identifiers returned 409. A lookup-by-request-ID endpoint is still absent from OpenAPI. NEXUS recovers a lost submit response by replaying the frozen query with the same run-derived identifiers until the Job ID is returned; a 409 remains a terminal conflict and must not be guessed into a Job ID.
3. Verified: pause returned HTTP 200 with `pausing` and later reached `paused`; resume returned HTTP 200 with `queued`/`desiredState=running`; terminal cancel returned 409. Active cancellation and `awaiting_human` were not exercised.
4. Verified: records are readable while the Job is running; an early read can be empty with a null cursor. After success, 49 records were read over five API pages with `limit=10`; the last page had a null cursor and replaying its input cursor returned the same nine records. Source pages 1-10 were present.
5. Verified: invalid record cursor returned 400, `limit=201` returned 422, and submit `pageLimit=31` returned 422. The live Job had a transient `agent_runtime_error` and recovered; exact meanings of all upstream failure codes and 403 behavior remain unverified.

The real deployment key must stay in a private Catalog outside version control when the adapter is implemented. C2 used it only for the live verification and did not add it to a repository file.
